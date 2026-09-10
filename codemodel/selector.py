"""Seletor de nodes no estilo do dbt: `dbt run --select +nome+`.

No dbt, `+nome` seleciona um model e todos os seus pais (upstream),
`nome+` seleciona o model e todos os seus filhos (downstream), e `+nome+`
seleciona os dois lados. Aqui replicamos essa sintaxe para escolher um
recorte do estado antes de renderizar ou inspecionar — útil quando o
código analisado é grande e você só quer ver a vizinhança de uma peça.

A seleção usa `parent_map`/`child_map` (dependências reais: import/calls)
para subir/descer o grafo, e sempre completa o resultado com a subárvore
estrutural (`contains`: módulo -> classe -> método) pra nunca devolver uma
caixa "vazia" sem o que ela contém, nem um filho órfão sem seu container.
"""
from __future__ import annotations

from typing import Optional


def resolve_selector(state: dict, selector: str) -> set[str]:
    include_parents = selector.startswith("+")
    include_children = selector.endswith("+")
    core = selector.strip("+")

    nodes = state["nodes"]
    parent_map = state.get("parent_map", {})
    child_map = state.get("child_map", {})

    matched = {nid for nid, n in nodes.items() if n["name"] == core or nid == core}
    if not matched:
        return set()

    result = set(matched)

    if include_parents:
        stack = list(matched)
        while stack:
            current = stack.pop()
            for parent in parent_map.get(current, []):
                if parent not in result:
                    result.add(parent)
                    stack.append(parent)

    if include_children:
        stack = list(matched)
        while stack:
            current = stack.pop()
            for child in child_map.get(current, []):
                if child not in result:
                    result.add(child)
                    stack.append(child)

    # subárvore estrutural (contains) descendo: classe/módulo selecionado
    # arrasta o que ele contém
    contains_children: dict[str, list[str]] = {}
    groups_children: dict[str, list[str]] = {}   # capability -> nodes de código que ela agrupa
    groups_parents: dict[str, list[str]] = {}     # node de código -> capabilities que o agrupam
    for edge in state["edges"]:
        if edge["type"] == "contains":
            contains_children.setdefault(edge["source"], []).append(edge["target"])
        elif edge["type"] == "groups":
            groups_children.setdefault(edge["source"], []).append(edge["target"])
            groups_parents.setdefault(edge["target"], []).append(edge["source"])

    stack = list(result)
    while stack:
        current = stack.pop()
        for child in contains_children.get(current, []):
            if child not in result:
                result.add(child)
                stack.append(child)

    # capability selecionada arrasta o código que ela agrupa, e código
    # selecionado arrasta a(s) capability(s) que o agrupam — assim
    # `--select nome_da_capability` mostra o código coberto, e selecionar
    # um módulo também revela sob qual funcionalidade percebida ele está
    stack = list(result)
    while stack:
        current = stack.pop()
        for child in groups_children.get(current, []):
            if child not in result:
                result.add(child)
                stack.append(child)
        for parent in groups_parents.get(current, []):
            if parent not in result:
                result.add(parent)
                stack.append(parent)

    # subárvore estrutural subindo: método/classe selecionado arrasta seu
    # container (senão a caixa não tem onde ser desenhada)
    stack = list(result)
    while stack:
        current = stack.pop()
        parent = nodes.get(current, {}).get("parent")
        if parent and parent not in result:
            result.add(parent)
            stack.append(parent)

    return result


def filter_state(state: dict, selector: Optional[str]) -> dict:
    """Devolve uma cópia do estado contendo só os nodes/edges selecionados.
    Sem selector, devolve o estado original sem cópia (mesmo objeto)."""
    if not selector:
        return state

    keep = resolve_selector(state, selector)
    filtered = dict(state)
    filtered["nodes"] = {
        nid: {**n, "depends_on": [d for d in n.get("depends_on", []) if d in keep]}
        for nid, n in state["nodes"].items() if nid in keep
    }
    filtered["edges"] = [e for e in state["edges"] if e["source"] in keep and e["target"] in keep]
    filtered["parent_map"] = {
        nid: [p for p in deps if p in keep]
        for nid, deps in state.get("parent_map", {}).items() if nid in keep
    }
    filtered["child_map"] = {
        nid: [c for c in deps if c in keep]
        for nid, deps in state.get("child_map", {}).items() if nid in keep
    }
    if "metadata" in state:
        filtered["metadata"] = dict(
            state["metadata"],
            node_count=len(filtered["nodes"]),
            edge_count=len(filtered["edges"]),
        )
    return filtered
