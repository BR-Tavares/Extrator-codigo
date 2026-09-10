"""Extração de código-fonte para o modelo de estado (JSON).

Estágios, nomeados como no dbt (parse -> compile):

  parse   percorre os arquivos .py com `ast` e registra módulos, classes,
          funções e métodos como nodes, com edges "contains" entre eles.
          Isso é só a estrutura sintática — não resolve nenhuma referência
          ainda, igual ao primeiro parse do dbt antes de resolver ref()/source().

  compile resolve imports e chamadas contra os nomes já registrados no
          parse, gerando os edges "import" e "calls". Só é possível depois
          que TODOS os módulos já passaram pelo parse (uma função em
          main.py pode chamar algo de service.py que só é conhecido depois
          de parsear service.py) — a mesma razão pela qual o dbt separa
          essas duas fases.

Depois disso, cada node ganha um `depends_on` (a lista de unique_ids dos
quais ele depende — import + calls, não contains) e o estado ganha
`parent_map` / `child_map` pré-computados, exatamente como o manifest.json
do dbt guarda esses dois mapas para navegação rápida do DAG sem precisar
percorrer a lista de edges toda vez.

Nodes de tipo `source` = dependências externas (imports de bibliotecas),
o equivalente às sources do dbt: dado bruto, de fora do projeto, nunca
analisado por dentro.

Limitações conhecidas (é uma prova de conceito, não um analisador completo):
- só Python, só sintaxe estática (sem `eval`, metaclasses dinâmicas, etc.);
- resolução de chamadas é heurística: nomes simples, `self.metodo()` dentro
  de uma classe, e `alias.funcao()` quando `alias` é um import conhecido.
  Chamadas mais indiretas (função guardada em variável, decorators
  dinâmicos, `getattr` etc.) não são capturadas;
- não segue call graphs entre pacotes fora do `root_path`.
"""
from __future__ import annotations

import ast
import os
from datetime import datetime, timezone
from typing import Optional

from . import ids


def _first_line(doc: Optional[str]) -> Optional[str]:
    if not doc:
        return None
    stripped = doc.strip().splitlines()
    return stripped[0].strip() if stripped else None


class Extractor:
    def __init__(self, root_path: str, project: Optional[str] = None):
        self.root_path = os.path.abspath(root_path)
        base_name = os.path.basename(self.root_path.rstrip(os.sep)) or "root"
        self.project = ids.sanitize_project(project or base_name)

        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []

        # Estruturas auxiliares só usadas durante a extração (não vão pro JSON final)
        self._func_ast_by_id: dict[str, ast.AST] = {}
        self._top_level_names: dict[str, dict[str, str]] = {}   # module_id -> {nome: node_id}
        self._class_methods: dict[str, dict[str, str]] = {}     # class_id  -> {nome: node_id}
        self._import_aliases: dict[str, dict[str, str]] = {}    # module_id -> {alias: target_id}
        self._func_class_context: dict[str, Optional[str]] = {} # func_id -> class_id (ou None)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        py_files = self._discover_files()
        module_infos = []  # (module_id, dotted_module, tree)

        # ---------------- estágio PARSE ----------------
        for filepath in py_files:
            dotted_module = self._dotted_module_for(filepath)
            module_id = ids.module_id(self.project, dotted_module)
            rel = os.path.relpath(filepath, self.root_path if os.path.isdir(self.root_path) else os.path.dirname(self.root_path))
            with open(filepath, "r", encoding="utf-8") as fh:
                source = fh.read()
            try:
                tree = ast.parse(source, filename=filepath)
            except SyntaxError as exc:
                self.nodes[module_id] = {
                    "id": module_id, "resource_type": "module",
                    "name": dotted_module, "file": rel,
                    "line_start": 1, "line_end": 1, "parent": None,
                    "docstring": f"[erro de sintaxe ao analisar: {exc}]",
                }
                continue

            self.nodes[module_id] = {
                "id": module_id, "resource_type": "module",
                "name": dotted_module, "file": rel,
                "line_start": 1, "line_end": getattr(tree, "end_lineno", None) or len(source.splitlines()),
                "parent": None, "docstring": _first_line(ast.get_docstring(tree)),
            }
            self._top_level_names[module_id] = {}
            module_infos.append((module_id, dotted_module, tree))

        known_dotted_modules = {dm for _, dm, _ in module_infos}

        for module_id, dotted_module, tree in module_infos:
            self._register_definitions(tree.body, module_id, dotted_module, parent_id=module_id, class_context=None)

        # ---------------- estágio COMPILE ----------------
        for module_id, dotted_module, tree in module_infos:
            self._register_imports(tree, module_id, known_dotted_modules)

        for func_id, func_ast in self._func_ast_by_id.items():
            self._register_calls(func_ast, func_id)

        self._compute_depends_on_and_maps()

        return {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "root_path": self.root_path,
                "project": self.project,
                "language": "python",
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
            },
            "nodes": self.nodes,
            "edges": self.edges,
            "parent_map": self._parent_map,
            "child_map": self._child_map,
        }

    # ------------------------------------------------------------------ #
    # Descoberta de arquivos
    # ------------------------------------------------------------------ #
    def _discover_files(self) -> list[str]:
        if os.path.isfile(self.root_path):
            return [self.root_path] if self.root_path.endswith(".py") else []
        result = []
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv", "node_modules")
            ]
            for name in filenames:
                if name.endswith(".py"):
                    result.append(os.path.join(dirpath, name))
        return sorted(result)

    def _dotted_module_for(self, filepath: str) -> str:
        base = self.root_path if os.path.isdir(self.root_path) else os.path.dirname(self.root_path)
        rel = os.path.relpath(filepath, base)
        rel = rel[:-3] if rel.endswith(".py") else rel
        dotted = rel.replace(os.sep, ".")
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        return dotted

    # ------------------------------------------------------------------ #
    # PARSE: definições (classes / funções / métodos)
    # ------------------------------------------------------------------ #
    def _register_definitions(self, body, module_id, dotted_module, parent_id, class_context):
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                class_id = ids.class_id(self.project, dotted_module, stmt.name)
                self.nodes[class_id] = {
                    "id": class_id, "resource_type": "class", "name": stmt.name,
                    "file": self.nodes[module_id]["file"],
                    "line_start": stmt.lineno, "line_end": getattr(stmt, "end_lineno", stmt.lineno),
                    "parent": parent_id, "docstring": _first_line(ast.get_docstring(stmt)),
                }
                self.edges.append({"source": parent_id, "target": class_id, "type": "contains"})
                if class_context is None:
                    self._top_level_names[module_id][stmt.name] = class_id
                self._class_methods[class_id] = {}
                self._register_definitions(stmt.body, module_id, dotted_module, parent_id=class_id, class_context=class_id)

            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if class_context is None:
                    func_id = ids.function_id(self.project, dotted_module, stmt.name)
                    kind = "function"
                else:
                    class_name = class_context.split(".")[-1]
                    func_id = ids.method_id(self.project, dotted_module, class_name, stmt.name)
                    kind = "method"

                self.nodes[func_id] = {
                    "id": func_id, "resource_type": kind, "name": stmt.name,
                    "file": self.nodes[module_id]["file"],
                    "line_start": stmt.lineno, "line_end": getattr(stmt, "end_lineno", stmt.lineno),
                    "parent": parent_id, "docstring": _first_line(ast.get_docstring(stmt)),
                    "args": [a.arg for a in stmt.args.args],
                }
                self.edges.append({"source": parent_id, "target": func_id, "type": "contains"})

                if class_context is None:
                    self._top_level_names[module_id][stmt.name] = func_id
                else:
                    self._class_methods[class_context][stmt.name] = func_id

                self._func_ast_by_id[func_id] = stmt
                self._func_class_context[func_id] = class_context
                # não descemos em funções aninhadas dentro de outras funções (fora do escopo do POC)

    # ------------------------------------------------------------------ #
    # COMPILE: imports
    # ------------------------------------------------------------------ #
    def _register_imports(self, tree, module_id, known_dotted_modules):
        aliases: dict[str, str] = {}
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    target = self._resolve_module_target(alias.name, known_dotted_modules)
                    aliases[alias.asname or alias.name.split(".")[0]] = target
                    self._add_import_edge(module_id, target)
            elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                target = self._resolve_module_target(stmt.module, known_dotted_modules)
                self._add_import_edge(module_id, target)
                for alias in stmt.names:
                    # "from x import y": se x é módulo conhecido E y é um nome de
                    # topo já registrado nele, o alias aponta direto pro node;
                    # senão cai no módulo (ou source) como um todo.
                    specific = self._top_level_names.get(target, {}).get(alias.name)
                    aliases[alias.asname or alias.name] = specific or target
        self._import_aliases[module_id] = aliases

    def _resolve_module_target(self, dotted_name: str, known_dotted_modules: set[str]) -> str:
        if dotted_name in known_dotted_modules:
            return ids.module_id(self.project, dotted_name)
        return ids.source_id(dotted_name)

    def _add_import_edge(self, module_id: str, target_id: str):
        if target_id.startswith("source.") and target_id not in self.nodes:
            self.nodes[target_id] = {
                "id": target_id, "resource_type": "source",
                "name": target_id.split(".", 2)[-1], "file": None,
                "line_start": None, "line_end": None, "parent": None,
                "docstring": "Dependência externa (não analisada — equivalente a uma source do dbt).",
            }
        if module_id != target_id:
            self.edges.append({"source": module_id, "target": target_id, "type": "import"})

    # ------------------------------------------------------------------ #
    # COMPILE: chamadas
    # ------------------------------------------------------------------ #
    def _register_calls(self, func_ast: ast.AST, func_id: str):
        module_id = ids.module_of(func_id)
        class_id = self._func_class_context.get(func_id)
        seen = set()

        for node in ast.walk(func_ast):
            if not isinstance(node, ast.Call):
                continue
            target_id = self._resolve_call_target(node.func, module_id, class_id)
            if target_id and target_id != func_id and (func_id, target_id) not in seen:
                seen.add((func_id, target_id))
                self.edges.append({"source": func_id, "target": target_id, "type": "calls"})

    def _resolve_call_target(self, func_expr: ast.AST, module_id: str, class_id: Optional[str]) -> Optional[str]:
        top_level = self._top_level_names.get(module_id, {})
        aliases = self._import_aliases.get(module_id, {})

        if isinstance(func_expr, ast.Name):
            name = func_expr.id
            return top_level.get(name) or aliases.get(name)

        if isinstance(func_expr, ast.Attribute):
            attr = func_expr.attr
            base = func_expr.value
            if isinstance(base, ast.Name):
                if base.id == "self" and class_id:
                    return self._class_methods.get(class_id, {}).get(attr)
                if base.id in aliases:
                    target = aliases[base.id]
                    if target.startswith("module."):
                        return self._top_level_names.get(target, {}).get(attr, target)
                    return target  # alvo externo (source) — chamada registrada de forma "grossa"
            return None

        return None

    # ------------------------------------------------------------------ #
    # depends_on por node + parent_map / child_map (à la dbt manifest)
    # ------------------------------------------------------------------ #
    def _compute_depends_on_and_maps(self):
        depends_on: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for edge in self.edges:
            if edge["type"] not in ("import", "calls"):
                continue
            deps = depends_on.setdefault(edge["source"], [])
            if edge["target"] not in deps:
                deps.append(edge["target"])

        for nid, deps in depends_on.items():
            self.nodes[nid]["depends_on"] = deps

        self._parent_map = depends_on
        child_map: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for nid, deps in depends_on.items():
            for dep in deps:
                if dep in child_map and nid not in child_map[dep]:
                    child_map[dep].append(nid)
        self._child_map = child_map
