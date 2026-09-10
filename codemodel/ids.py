"""Esquema de identificadores, no formato do dbt: `<resource_type>.<project>.<nome_qualificado>`.

No manifest.json do dbt, todo node tem um `unique_id` assim, por exemplo
`model.jaffle_shop.customers` ou `source.jaffle_shop.raw.orders` — o
primeiro segmento é o tipo de recurso, o segundo é o projeto/pacote de
onde ele vem, e o resto é o nome qualificado dentro daquele projeto.
Isso permite, por exemplo, diferenciar um `model` do projeto local de um
`model` vindo de um pacote instalado (cross-project refs).

Aqui replicamos a mesma ideia para código: dependências externas (imports
de bibliotecas) viram `source.external.<nome>` — o equivalente a uma
source do dbt: dado bruto, de fora do projeto, não analisado.
"""
from __future__ import annotations

import re
from typing import Optional

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]+")


def sanitize_project(name: str) -> str:
    """Garante que o nome do projeto nunca contenha pontos (usamos o ponto
    como separador dentro do unique_id, então o project precisa ser opaco)."""
    cleaned = _SANITIZE_RE.sub("_", name).strip("_")
    return cleaned or "root"


def module_id(project: str, dotted_module: str) -> str:
    return f"module.{project}.{dotted_module}"


def class_id(project: str, dotted_module: str, class_name: str) -> str:
    return f"class.{project}.{dotted_module}.{class_name}"


def function_id(project: str, dotted_module: str, func_name: str) -> str:
    return f"function.{project}.{dotted_module}.{func_name}"


def method_id(project: str, dotted_module: str, class_name: str, method_name: str) -> str:
    return f"method.{project}.{dotted_module}.{class_name}.{method_name}"


def source_id(dotted_import_name: str) -> str:
    # dependências externas não pertencem ao projeto analisado — usamos o
    # pseudo-projeto "external", do mesmo jeito que o dbt usa o nome do
    # pacote de origem para refs entre projetos
    return f"source.external.{dotted_import_name}"


def capability_id(project: str, slug: str) -> str:
    # camada perceptual/funcional, no espírito das "exposures" do dbt:
    # nunca gerada pelo parser, sempre curada (proposta + aprovada)
    return f"capability.{project}.{slug}"


def parse_id(unique_id: str) -> tuple[str, str, str]:
    """Devolve (resource_type, project, nome_qualificado)."""
    kind, rest = unique_id.split(".", 1)
    if "." not in rest:
        return kind, rest, ""
    project, qualified = rest.split(".", 1)
    return kind, project, qualified


def module_of(unique_id: str) -> Optional[str]:
    """Dado o id de qualquer node, devolve o id do módulo que o contém.
    Devolve None para `source` (não pertence a nenhum módulo do projeto)."""
    kind, project, qualified = parse_id(unique_id)
    if kind == "module":
        return unique_id
    if kind == "source":
        return None
    parts = qualified.split(".")
    cut = 2 if kind == "method" else 1  # method: Classe.metodo -> corta 2; class/function: corta 1
    mod_qualified = ".".join(parts[:-cut]) if len(parts) > cut else parts[0]
    return module_id(project, mod_qualified)
