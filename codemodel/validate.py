"""Validação estrutural do estado — a etapa "Validate" do pipeline do Archify.

O Archify roda uma checagem de schema e de regras de layout ANTES de
renderizar, e só entrega o artefato se ela passar. Aqui fazemos o
equivalente, mas validando a estrutura do nosso JSON (não um schema
externo formal, para manter a POC sem dependências): todo edge aponta
para nodes que existem, todo `parent` existe, todo `depends_on` bate com
os edges, o prefixo de cada unique_id bate com o `resource_type` do node
(a convenção de id do dbt só funciona se for mantida à risca).
"""
from __future__ import annotations


def validate_state(state: dict) -> list[str]:
    problems: list[str] = []
    nodes = state.get("nodes", {})

    for nid, node in nodes.items():
        if node.get("id") != nid:
            problems.append(f"node '{nid}': campo 'id' ('{node.get('id')}') não bate com a chave")

        prefix = nid.split(".", 1)[0]
        if node.get("resource_type") != prefix:
            problems.append(
                f"node '{nid}': resource_type '{node.get('resource_type')}' não bate com o prefixo do id ('{prefix}')"
            )

        parent = node.get("parent")
        if parent and parent not in nodes:
            problems.append(f"node '{nid}': parent '{parent}' não existe em nodes")

        for dep in node.get("depends_on", []):
            if dep not in nodes:
                problems.append(f"node '{nid}': depends_on aponta pra id inexistente '{dep}'")

        if node.get("resource_type") == "capability":
            if not node.get("depends_on"):
                problems.append(f"capability '{nid}': não agrupa nenhum node de código (depends_on vazio)")
            for dep in node.get("depends_on", []):
                dep_node = nodes.get(dep)
                if dep_node and dep_node["resource_type"] not in ("module", "class", "function", "method"):
                    problems.append(
                        f"capability '{nid}': agrupa '{dep}', que não é código (é '{dep_node['resource_type']}')"
                    )
            if not node.get("origin", {}).get("approved_by"):
                problems.append(f"capability '{nid}': sem 'origin.approved_by' — capability precisa de aprovação registrada")

    for i, edge in enumerate(state.get("edges", [])):
        if edge.get("source") not in nodes:
            problems.append(f"edge #{i} ({edge.get('type')}): source '{edge.get('source')}' não existe")
        if edge.get("target") not in nodes:
            problems.append(f"edge #{i} ({edge.get('type')}): target '{edge.get('target')}' não existe")

    parent_map = state.get("parent_map", {})
    child_map = state.get("child_map", {})
    for nid, deps in parent_map.items():
        for dep in deps:
            if nid not in child_map.get(dep, []):
                problems.append(f"parent_map/child_map inconsistentes: '{nid}' depende de '{dep}', mas child_map['{dep}'] não lista '{nid}' de volta")

    return problems
