"""CLI da prova de conceito.

Além do pipeline original (extract -> validate -> render -> check),
agora existem:

  codemodel snapshot <state.json> [-m msg]
      git add + git commit do arquivo de estado. `extract`/`approve`
      já chamam isso sozinhos por padrão (desligue com --no-git).

  codemodel propose-template <state.json> [--out proposal.json]
      gera um esqueleto de proposta de `capability` (funcionalidade
      percebida pelo usuário) listando os nodes de código disponíveis
      pra agrupar. Quem preenche o agrupamento em si é uma IA ou um
      humano lendo o código — isso é julgamento, a ferramenta não inventa.

  codemodel validate-proposal <proposal.json> --state <state.json>
      confere se a proposta é estruturalmente válida antes de aprovar.

  codemodel approve <proposal.json> --state <state.json> --by "quem"
      funde a proposta no estado (cria os nodes `capability` + edges
      `groups`), carimba `origin.approved_by`, salva e comita.

`extract` (e `run`, que chama `extract` por baixo) agora faz *merge*
em vez de sobrescrever: capabilities já aprovadas numa rodada anterior
sobrevivem à reextração, desde que todo o código que elas agrupam ainda
exista. O extractor em si nunca soube disso — o merge é responsabilidade
da CLI, não do extractor (ver `_extract_and_merge` abaixo).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import versioning
from .checks import check_geometry
from .extractor import Extractor
from .html import wrap_svg_in_html, wrap_state_in_viewer
from .proposal import apply_proposal, generate_template, validate_proposal
from .renderer import Renderer
from .selector import filter_state
from .state import load_state, save_state
from .validate import validate_state


def _print_problems(problems: list[str], label: str) -> None:
    print(f"[{label}] {len(problems)} problema(s) encontrado(s):")
    for p in problems:
        print(f"  - {p}")


def _git_snapshot(path: str, state: dict, label: str, enabled: bool, message: str | None) -> None:
    if not enabled:
        return
    msg = message or versioning.auto_message(path, state["metadata"]["node_count"], label=label)
    ok, info = versioning.snapshot(path, msg)
    tag = "git" if ok else "git (aviso)"
    print(f"[{tag}] {info}")


def _extract_and_merge(path: str, out: str, project: str | None) -> dict:
    """Roda o extractor e funde o resultado com as `capability` já
    aprovadas num state.json existente (se houver). O extractor é dono
    de tudo que não é `capability`; capabilities são preservadas tal
    como estavam, desde que todo o código que agrupam continue existindo
    — senão são descartadas, com aviso, porque não faz sentido manter uma
    capability apontando pra código que não existe mais."""
    new_state = Extractor(path, project=project).run()

    try:
        old_state = load_state(out)
    except (FileNotFoundError, json.JSONDecodeError):
        old_state = None

    if old_state:
        kept, dropped = 0, []
        for nid, node in old_state.get("nodes", {}).items():
            if node.get("resource_type") != "capability":
                continue
            missing = [d for d in node.get("depends_on", []) if d not in new_state["nodes"]]
            if missing:
                dropped.append((nid, missing))
                continue
            new_state["nodes"][nid] = node
            for edge in old_state["edges"]:
                if edge["source"] == nid and edge["type"] == "groups":
                    new_state["edges"].append(edge)
            kept += 1

        if kept:
            print(f"[merge] {kept} capability(s) preservada(s) da extração anterior")
        for nid, missing in dropped:
            print(f"[merge] capability '{nid}' descartada: código que ela agrupava não existe mais ({', '.join(missing)})")

        new_state["metadata"]["node_count"] = len(new_state["nodes"])
        new_state["metadata"]["edge_count"] = len(new_state["edges"])

    return new_state


def _render_pipeline(state: dict, out_path: str, fmt: str, select: str | None) -> bool:
    """Roda select -> validate -> render -> check. Devolve True se ok."""
    scoped = filter_state(state, select)

    problems = validate_state(scoped)
    if problems:
        _print_problems(problems, "validate")
        return False
    print(f"[validate] estado ok ({len(scoped['nodes'])} nodes, {len(scoped['edges'])} edges)")

    renderer = Renderer(scoped)
    svg = renderer.render()

    geo_problems = check_geometry(renderer.boxes)
    if geo_problems:
        _print_problems(geo_problems, "check")
        return False
    print(f"[check] geometria ok ({len(renderer.boxes)} caixas)")

    meta = scoped.get("metadata", {})
    if fmt == "html":
        title = f"codemodel — {meta.get('project', '')}"
        meta_line = f"{meta.get('node_count', '?')} nodes · {meta.get('edge_count', '?')} edges · gerado em {meta.get('generated_at', '?')}"
        content = wrap_svg_in_html(svg, title, meta_line)
    else:
        content = svg

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True


# ---------------------------------------------------------------------- #
# comandos
# ---------------------------------------------------------------------- #
def cmd_extract(args) -> int:
    state = _extract_and_merge(args.path, args.out, args.project)
    out = save_state(state, args.out)
    meta = state["metadata"]
    print(f"[parse+compile] {meta['node_count']} nodes, {meta['edge_count']} edges -> {out}")
    _git_snapshot(args.out, state, "extract", args.git, args.message)
    return 0


def cmd_validate(args) -> int:
    state = load_state(args.state_path)
    problems = validate_state(state)
    if problems:
        _print_problems(problems, "validate")
        return 1
    print(f"[validate] estado ok ({len(state['nodes'])} nodes, {len(state['edges'])} edges)")
    return 0


def cmd_render(args) -> int:
    state = load_state(args.state_path)
    out_path = args.out or ("diagram.html" if args.format == "html" else "diagram.svg")
    if not _render_pipeline(state, out_path, args.format, args.select):
        return 1
    print(f"[render] {args.state_path} -> {out_path}")
    return 0


def cmd_run(args) -> int:
    state = _extract_and_merge(args.path, args.state, args.project)
    save_state(state, args.state)
    meta = state["metadata"]
    print(f"[parse+compile] {meta['node_count']} nodes, {meta['edge_count']} edges -> {args.state}")

    out_path = args.out or ("diagram.html" if args.format == "html" else "diagram.svg")
    if not _render_pipeline(state, out_path, args.format, args.select):
        return 1
    print(f"[render] -> {out_path}")
    _git_snapshot(args.state, state, "extract", args.git, args.message)
    return 0


def cmd_show(args) -> int:
    state = load_state(args.state_path)
    scoped = filter_state(state, args.select)

    by_type: dict[str, list[str]] = {}
    for node in scoped["nodes"].values():
        by_type.setdefault(node["resource_type"], []).append(node["name"])

    meta = scoped.get("metadata", state.get("metadata", {}))
    print(f"projeto: {meta.get('project')}")
    print(f"root_path: {meta.get('root_path')}")
    print(f"gerado em: {meta.get('generated_at')}")
    if args.select:
        print(f"seleção: {args.select} ({len(scoped['nodes'])} de {len(state['nodes'])} nodes)")

    for kind in ("capability", "module", "class", "function", "method", "source"):
        names = by_type.get(kind, [])
        print(f"\n{kind} ({len(names)}):")
        for name in names:
            print(f"  - {name}")

    edge_counts: dict[str, int] = {}
    for edge in scoped["edges"]:
        edge_counts[edge["type"]] = edge_counts.get(edge["type"], 0) + 1
    print("\nedges:", edge_counts)
    return 0


def cmd_view(args) -> int:
    state = load_state(args.state_path)
    out_path = args.out or "index.html"
    meta = state.get("metadata", {})
    title = f"codemodel — {meta.get('project', '')}"
    content = wrap_state_in_viewer(state, title)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    n = len(state.get("nodes", {}))
    e = len(state.get("edges", []))
    print(f"[view] {n} nodes, {e} edges -> {out_path}")
    return 0


def cmd_snapshot(args) -> int:
    ok, info = versioning.snapshot(args.state_path, args.message or "snapshot manual")
    print(f"[{'git' if ok else 'git (erro)'}] {info}")
    return 0 if ok else 1


def cmd_propose_template(args) -> int:
    state = load_state(args.state_path)
    template = generate_template(state)
    save_state(template, args.out)
    print(f"[propose-template] {len(template['candidates'])} candidatos listados -> {args.out}")
    print("Preencha 'capabilities' nesse arquivo (a ferramenta não sugere agrupamentos: isso é julgamento).")
    return 0


def cmd_validate_proposal(args) -> int:
    proposal = load_state(args.proposal_path)
    state = load_state(args.state)
    problems = validate_proposal(proposal, state)
    if problems:
        _print_problems(problems, "validate-proposal")
        return 1
    print(f"[validate-proposal] ok ({len(proposal.get('capabilities', []))} capability(s))")
    return 0


def cmd_approve(args) -> int:
    proposal = load_state(args.proposal_path)
    state = load_state(args.state)

    problems = validate_proposal(proposal, state)
    if problems:
        _print_problems(problems, "validate-proposal")
        print("[approve] abortado: corrija a proposta antes de aprovar")
        return 1

    new_state = apply_proposal(state, proposal, approved_by=args.by)

    struct_problems = validate_state(new_state)
    if struct_problems:
        _print_problems(struct_problems, "validate")
        print("[approve] abortado: estado resultante ficaria inconsistente")
        return 1

    save_state(new_state, args.state)
    slugs = [c["slug"] for c in proposal["capabilities"]]
    print(f"[approve] {len(slugs)} capability(s) aprovada(s) por '{args.by}': {', '.join(slugs)}")
    _git_snapshot(args.state, new_state, f"approve capabilities by {args.by}", args.git, args.message)
    return 0


# ---------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codemodel",
        description="POC: código -> estado (JSON, à la dbt) -> diagrama (HTML/SVG, à la Archify), com capabilities aprovadas e git.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="código -> estado (JSON), preservando capabilities já aprovadas")
    p_extract.add_argument("path", help="arquivo .py ou diretório a analisar")
    p_extract.add_argument("--out", default="state.json", help="caminho de saída/entrada do JSON (default: state.json)")
    p_extract.add_argument("--project", default=None, help="nome do projeto (default: nome do diretório/arquivo analisado)")
    p_extract.add_argument("--git", action=argparse.BooleanOptionalAction, default=True, help="commita o estado após salvar (default: sim)")
    p_extract.add_argument("--message", "-m", default=None, help="mensagem de commit (default: gerada automaticamente)")
    p_extract.set_defaults(func=cmd_extract)

    p_validate = sub.add_parser("validate", help="valida a estrutura de um estado já extraído")
    p_validate.add_argument("state_path", help="caminho do state.json")
    p_validate.set_defaults(func=cmd_validate)

    p_render = sub.add_parser("render", help="estado (JSON) -> diagrama (validate -> render -> check)")
    p_render.add_argument("state_path", help="caminho do state.json")
    p_render.add_argument("--out", default=None, help="caminho de saída (default: diagram.html ou diagram.svg)")
    p_render.add_argument("--format", choices=["html", "svg"], default="html", help="formato de saída (default: html)")
    p_render.add_argument("--select", default=None, help="seletor estilo dbt: nome | +nome | nome+ | +nome+")
    p_render.set_defaults(func=cmd_render)

    p_run = sub.add_parser("run", help="pipeline completo: extract -> validate -> render -> check")
    p_run.add_argument("path", help="arquivo .py ou diretório a analisar")
    p_run.add_argument("--state", default="state.json", help="caminho de saída/entrada do JSON (default: state.json)")
    p_run.add_argument("--out", default=None, help="caminho de saída do diagrama (default: diagram.html ou diagram.svg)")
    p_run.add_argument("--format", choices=["html", "svg"], default="html", help="formato de saída (default: html)")
    p_run.add_argument("--select", default=None, help="seletor estilo dbt: nome | +nome | nome+ | +nome+")
    p_run.add_argument("--project", default=None, help="nome do projeto (default: nome do diretório/arquivo analisado)")
    p_run.add_argument("--git", action=argparse.BooleanOptionalAction, default=True, help="commita o estado após salvar (default: sim)")
    p_run.add_argument("--message", "-m", default=None, help="mensagem de commit (default: gerada automaticamente)")
    p_run.set_defaults(func=cmd_run)

    p_show = sub.add_parser("show", help="resumo legível de um estado já extraído (um `dbt ls` simplificado)")
    p_show.add_argument("state_path", help="caminho do state.json")
    p_show.add_argument("--select", default=None, help="seletor estilo dbt: nome | +nome | nome+ | +nome+")
    p_show.set_defaults(func=cmd_show)

    p_snapshot = sub.add_parser("snapshot", help="git add + commit manual do state.json")
    p_snapshot.add_argument("state_path", help="caminho do state.json")
    p_snapshot.add_argument("--message", "-m", default=None, help="mensagem de commit")
    p_snapshot.set_defaults(func=cmd_snapshot)

    p_tmpl = sub.add_parser("propose-template", help="gera um esqueleto de proposta de capability")
    p_tmpl.add_argument("state_path", help="caminho do state.json")
    p_tmpl.add_argument("--out", default="proposal.json", help="caminho de saída (default: proposal.json)")
    p_tmpl.set_defaults(func=cmd_propose_template)

    p_vprop = sub.add_parser("validate-proposal", help="valida uma proposta de capability contra um estado")
    p_vprop.add_argument("proposal_path", help="caminho do proposal.json")
    p_vprop.add_argument("--state", required=True, help="caminho do state.json contra o qual validar")
    p_vprop.set_defaults(func=cmd_validate_proposal)

    p_approve = sub.add_parser("approve", help="funde uma proposta validada no estado (cria as capabilities)")
    p_approve.add_argument("proposal_path", help="caminho do proposal.json")
    p_approve.add_argument("--state", required=True, help="caminho do state.json a atualizar")
    p_approve.add_argument("--by", required=True, help="quem está aprovando (nome ou identificador)")
    p_approve.add_argument("--git", action=argparse.BooleanOptionalAction, default=True, help="commita o estado após aprovar (default: sim)")
    p_approve.add_argument("--message", "-m", default=None, help="mensagem de commit (default: gerada automaticamente)")
    p_approve.set_defaults(func=cmd_approve)

    p_view = sub.add_parser("view", help="viewer interativo do state.json (Cytoscape.js, pan/zoom/busca/filtro)")
    p_view.add_argument("state_path", help="caminho do state.json")
    p_view.add_argument("--out", default="index.html", help="caminho de saída (default: index.html)")
    p_view.set_defaults(func=cmd_view)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
