"""Capacidades: a camada de funcionalidade percebida pelo usuário, no
espírito das "exposures" do dbt (docs.getdbt.com/reference/exposure-properties).

Uma exposure do dbt é declarada à mão (YAML), nunca inferida do SQL, e
aponta pra models existentes via `depends_on: [ref(...), ...]` — ela documenta
como models são consumidos por fora (um dashboard, uma API), sem nunca
virar parte do grafo de models em si.

Aqui o paralelo é direto: o extractor decompõe código em módulo/classe/
função — uma fronteira de IMPLEMENTAÇÃO. Quase nunca essa fronteira bate
com o que o usuário percebe como "uma funcionalidade". Uma `capability`
é essa camada por cima: agrupa nodes de código existentes sob um nome e
descrição do ponto de vista de quem usa o sistema, sem alterar nenhum
node de código.

Como isso é julgamento (não um fato verificável estaticamente), o fluxo
tem uma etapa de aprovação obrigatória:

  1. propose  : alguém (IA ou humano) escreve um proposal.json com uma
                lista de capabilities candidatas, cada uma listando quais
                ids de código ela agrupa e por quê (rationale).
  2. validate : confere que a proposta é estruturalmente válida contra o
                estado atual (ids existem, são nodes de código, campos
                obrigatórios presentes).
  3. approve  : só então a proposta vira parte do estado — carimbada com
                quem propôs, quem aprovou e quando (`origin`).

O extractor nunca lê nem escreve capabilities; a extração seguinte
preserva as que já foram aprovadas (ver `cli.py::_extract_and_merge`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import ids

CODE_TYPES = ("module", "class", "function", "method")


def generate_template(state: dict) -> dict:
    """Monta um esqueleto de proposta com a lista de nodes de código do
    estado atual, pra quem for escrever a proposta não precisar catalogar
    os ids manualmente. Não sugere nenhum agrupamento — isso é julgamento,
    não algo que o lado determinístico da ferramenta deveria inventar."""
    candidates = [
        {"id": n["id"], "resource_type": n["resource_type"], "name": n["name"]}
        for n in state["nodes"].values()
        if n["resource_type"] in CODE_TYPES
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on_project": state.get("metadata", {}).get("project"),
        "based_on_node_count": state.get("metadata", {}).get("node_count"),
        "proposed_by": "ai",
        "instructions": (
            "Preencha 'capabilities'. Cada item agrupa um ou mais ids de "
            "'candidates' numa funcionalidade do ponto de vista de quem usa "
            "o sistema — não repita a estrutura de arquivos/classes, "
            "questione-a: o que o usuário enxerga como uma coisa só, mesmo "
            "estando espalhado em vários módulos de código?"
        ),
        "candidates": candidates,
        "capabilities": [],
    }


def validate_proposal(proposal: dict, state: dict) -> list[str]:
    problems: list[str] = []
    nodes = state.get("nodes", {})
    seen_slugs: set[str] = set()

    capabilities = proposal.get("capabilities", [])
    if not capabilities:
        problems.append("proposta não tem nenhuma capability em 'capabilities'")

    for i, cap in enumerate(capabilities):
        for field in ("slug", "name", "description", "groups"):
            if not cap.get(field):
                problems.append(f"capability #{i}: campo obrigatório '{field}' ausente ou vazio")

        slug = cap.get("slug")
        if slug:
            if slug in seen_slugs:
                problems.append(f"capability #{i}: slug '{slug}' duplicado dentro da própria proposta")
            seen_slugs.add(slug)

        for group_id in cap.get("groups", []):
            node = nodes.get(group_id)
            if node is None:
                problems.append(f"capability '{slug}': id '{group_id}' em 'groups' não existe no estado")
            elif node["resource_type"] not in CODE_TYPES:
                problems.append(
                    f"capability '{slug}': '{group_id}' não é um node de código "
                    f"(é '{node['resource_type']}') — capability só agrupa código, não outra capability ou source"
                )

    return problems


def apply_proposal(state: dict, proposal: dict, approved_by: str) -> dict:
    """Funde uma proposta já validada no estado. Cria/atualiza um node
    `capability` por item, mais os edges `groups` correspondentes. Devolve
    um novo dict de estado (não modifica `state` in place)."""
    project = state.get("metadata", {}).get("project", "root")
    now = datetime.now(timezone.utc).isoformat()

    new_state = dict(state)
    new_state["nodes"] = dict(state["nodes"])
    new_state["edges"] = list(state["edges"])

    for cap in proposal["capabilities"]:
        cid = ids.capability_id(project, cap["slug"])

        # se for uma reaprovação (slug já existente), substitui os edges
        # "groups" antigos dessa capability em vez de duplicar
        new_state["edges"] = [
            e for e in new_state["edges"] if not (e["source"] == cid and e["type"] == "groups")
        ]

        previous = state["nodes"].get(cid)
        origin = {
            "proposed_by": proposal.get("proposed_by", "ai"),
            "approved_by": approved_by,
            "approved_at": now,
            "rationale": cap.get("rationale"),
        }
        if previous and previous.get("origin", {}).get("approved_at"):
            origin["previously_approved_at"] = previous["origin"]["approved_at"]

        new_state["nodes"][cid] = {
            "id": cid, "resource_type": "capability", "name": cap["name"],
            "file": None, "line_start": None, "line_end": None, "parent": None,
            "docstring": cap["description"],
            "depends_on": list(cap["groups"]),
            "origin": origin,
        }
        for group_id in cap["groups"]:
            new_state["edges"].append({"source": cid, "target": group_id, "type": "groups"})

    new_state["metadata"] = dict(
        state.get("metadata", {}),
        node_count=len(new_state["nodes"]),
        edge_count=len(new_state["edges"]),
    )
    return new_state
