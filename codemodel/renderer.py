"""Renderização do estado (JSON) em um diagrama SVG.

Ideia inspirada no Archify: o SVG nunca é gerado direto do código-fonte —
ele é sempre gerado a partir do "state" (o JSON), que é o mesmo artefato
usado por qualquer outra visualização futura. Trocar o layout, os estilos
ou até o formato de saída (ex.: um exportador C4) não deveria exigir tocar
no extractor: só este arquivo.

Layout (deliberadamente simples, para ficar fácil de entender e estender):

  [ sources (deps externas) ]      <- fileira de pílulas no topo
              |
              v
  [ módulo A ]   [ módulo B ]      <- módulos em fluxo (wrap), cada um
    - Classe X       - função foo   contendo suas classes/funções, e cada
        - método a                  classe contendo seus métodos
        - método b
    - função bar

Arestas "import" ligam módulo -> módulo/source.
Arestas "calls" ligam função/método -> função/método/source (tracejada).
Arestas "contains" não são desenhadas como seta: já estão implícitas no
aninhamento visual das caixas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------- #
# Constantes de layout
# ---------------------------------------------------------------------- #
PADDING = 12
MODULE_W = 280
MODULE_HEADER_H = 28
CLASS_HEADER_H = 22
ROW_H = 24
ROW_GAP = 6
BLOCK_GAP = 10
MODULE_GAP_X = 50
MODULE_GAP_Y = 60
SOURCE_H = 32
SOURCE_GAP = 24
CANVAS_MAX_W = 1500
MARGIN = 40

COLORS = {
    "module": ("#eef2ff", "#4338ca"),
    "class": ("#ecfeff", "#0e7490"),
    "function": ("#f0fdf4", "#15803d"),
    "method": ("#fefce8", "#a16207"),
    "source": ("#fef2f2", "#b91c1c"),
    "capability": ("#f5f3ff", "#6d28d9"),
}


@dataclass
class Box:
    id: str
    x: float
    y: float
    w: float
    h: float
    label: str
    kind: str
    sub: str = ""

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2


def _truncate(text: str, max_chars: int) -> str:
    if text is None:
        return ""
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class Renderer:
    def __init__(self, state: dict):
        self.state = state
        self.nodes: dict[str, dict] = state["nodes"]
        self.edges: list[dict] = state["edges"]
        self.boxes: dict[str, Box] = {}

    # ------------------------------------------------------------------ #
    def render(self) -> str:
        modules = [n for n in self.nodes.values() if n["resource_type"] == "module"]
        sources = [n for n in self.nodes.values() if n["resource_type"] == "source"]
        capabilities = [n for n in self.nodes.values() if n["resource_type"] == "capability"]
        children_by_parent = self._children_by_parent()

        modules.sort(key=lambda m: m["name"])
        capabilities.sort(key=lambda c: c["name"])

        # --- cabeçalho-resumo (equivalente a um "card" do Archify) ---
        header_h = 34
        meta = self.state.get("metadata", {})
        header_text = (
            f"{meta.get('project', '')} — {meta.get('node_count', len(self.nodes))} nodes, "
            f"{meta.get('edge_count', len(self.edges))} edges"
        )

        # --- posiciona a fileira de capabilities no topo de tudo (é a
        # camada mais "percebida pelo usuário", por isso fica acima até
        # das sources) ---
        cap_y = MARGIN + header_h
        cursor_x = MARGIN
        for cap in capabilities:
            w = max(140, 11 * len(_truncate(cap["name"], 30)))
            box = Box(cap["id"], cursor_x, cap_y, w, SOURCE_H, _truncate(cap["name"], 30), "capability")
            self.boxes[cap["id"]] = box
            cursor_x += w + SOURCE_GAP

        # --- posiciona a fileira de sources ---
        source_y = cap_y + (SOURCE_H + 40 if capabilities else 0)
        cursor_x = MARGIN
        for src in sources:
            w = max(90, 12 * len(_truncate(src["name"], 22)))
            box = Box(src["id"], cursor_x, source_y, w, SOURCE_H, _truncate(src["name"], 22), "source")
            self.boxes[src["id"]] = box
            cursor_x += w + SOURCE_GAP

        # --- posiciona os módulos em fluxo (wrap) ---
        modules_top = source_y + (SOURCE_H + 50 if sources else 0)
        cursor_x = MARGIN
        cursor_y = modules_top
        row_max_h = 0

        for mod in modules:
            mod_h = self._layout_module(mod, children_by_parent, dry_run=True)
            if cursor_x + MODULE_W > CANVAS_MAX_W and cursor_x > MARGIN:
                cursor_x = MARGIN
                cursor_y += row_max_h + MODULE_GAP_Y
                row_max_h = 0
            self._layout_module(mod, children_by_parent, x=cursor_x, y=cursor_y)
            row_max_h = max(row_max_h, mod_h)
            cursor_x += MODULE_W + MODULE_GAP_X

        widest_row = max(len(sources) * (SOURCE_GAP + 90), len(capabilities) * (SOURCE_GAP + 140))
        canvas_w = min(CANVAS_MAX_W, max(cursor_x, MARGIN + widest_row)) + MARGIN
        canvas_h = cursor_y + row_max_h + MARGIN

        return self._to_svg(canvas_w, canvas_h, header_text)


    # ------------------------------------------------------------------ #
    def _children_by_parent(self) -> dict[str, list[dict]]:
        by_parent: dict[str, list[dict]] = {}
        for edge in self.edges:
            if edge["type"] != "contains":
                continue
            by_parent.setdefault(edge["source"], []).append(self.nodes[edge["target"]])
        for children in by_parent.values():
            children.sort(key=lambda n: n.get("line_start") or 0)
        return by_parent

    def _layout_module(self, mod, children_by_parent, x=0.0, y=0.0, dry_run=False) -> float:
        """Calcula (e, se não for dry_run, registra em self.boxes) a caixa do
        módulo e de tudo que ele contém. Retorna a altura total do módulo."""
        children = children_by_parent.get(mod["id"], [])
        cursor_y = y + MODULE_HEADER_H + PADDING

        for child in children:
            if child["resource_type"] == "function":
                if not dry_run:
                    self.boxes[child["id"]] = Box(
                        child["id"], x + PADDING, cursor_y, MODULE_W - 2 * PADDING, ROW_H,
                        _truncate(child["name"] + "()", 28), "function",
                    )
                cursor_y += ROW_H + ROW_GAP

            elif child["resource_type"] == "class":
                methods = children_by_parent.get(child["id"], [])
                class_top = cursor_y
                if not dry_run:
                    pass  # a caixa da classe é registrada depois de sabermos a altura total
                method_y = class_top + CLASS_HEADER_H + 4
                for m in methods:
                    if not dry_run:
                        self.boxes[m["id"]] = Box(
                            m["id"], x + PADDING * 2, method_y, MODULE_W - 4 * PADDING, ROW_H - 2,
                            _truncate(m["name"] + "()", 24), "method",
                        )
                    method_y += (ROW_H - 2) + 4
                class_h = (CLASS_HEADER_H + 4) + len(methods) * ((ROW_H - 2) + 4) + 6
                if not dry_run:
                    self.boxes[child["id"]] = Box(
                        child["id"], x + PADDING, class_top, MODULE_W - 2 * PADDING, class_h,
                        _truncate(child["name"], 26), "class",
                    )
                cursor_y = class_top + class_h + BLOCK_GAP

        total_h = (cursor_y - y) + PADDING
        if not dry_run:
            self.boxes[mod["id"]] = Box(mod["id"], x, y, MODULE_W, total_h, _truncate(mod["name"], 30), "module")
        return total_h

    # ------------------------------------------------------------------ #
    def _to_svg(self, w: float, h: float, header_text: str = "") -> str:
        parts: list[str] = []
        parts.append(
            f'<svg viewBox="0 0 {w:.0f} {h:.0f}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="Helvetica, Arial, sans-serif">'
        )
        parts.append(self._defs())
        parts.append(f'<rect x="0" y="0" width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>')
        if header_text:
            parts.append(
                f'<text class="header-text" x="{MARGIN}" y="{MARGIN + 14}" font-size="13" '
                f'font-weight="600" fill="#334155">{_esc(header_text)}</text>'
            )

        # arestas primeiro (para ficarem atrás das caixas)
        for edge in self.edges:
            if edge["type"] == "contains":
                continue
            parts.append(self._render_edge(edge))

        # depois módulos (para servirem de "fundo" dos filhos) e por fim classes/funções/sources
        order = {"module": 0, "source": 0, "capability": 0, "class": 1, "function": 2, "method": 2}
        for box in sorted(self.boxes.values(), key=lambda b: order.get(b.kind, 3)):
            parts.append(self._render_box(box))

        parts.append("</svg>")
        return "\n".join(parts)

    def _defs(self) -> str:
        return """
<defs>
  <marker id="arrow-import" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#6366f1"/>
  </marker>
  <marker id="arrow-call" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#16a34a"/>
  </marker>
  <marker id="arrow-groups" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#7c3aed"/>
  </marker>
</defs>
""".strip()

    def _render_box(self, box: Box) -> str:
        fill, stroke = COLORS.get(box.kind, ("#f5f5f5", "#333333"))
        rx = 10 if box.kind in ("module", "source", "capability") else 6
        label_y = box.y + (MODULE_HEADER_H / 2 + 5 if box.kind == "module" else box.h / 2 + 4)
        weight = "600" if box.kind in ("module", "class", "capability") else "400"
        size = 13 if box.kind == "module" else (12 if box.kind in ("class", "capability") else 11)
        dash = ' stroke-dasharray="5,2"' if box.kind == "capability" else ""
        return (
            f'<g>'
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.3"{dash}/>'
            f'<text x="{box.x + 10:.1f}" y="{label_y:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{stroke}">{_esc(box.label)}</text>'
            f'</g>'
        )

    def _render_edge(self, edge: dict) -> str:
        src = self.boxes.get(edge["source"])
        tgt = self.boxes.get(edge["target"])
        if not src or not tgt or src.id == tgt.id:
            return ""
        if edge["type"] == "import":
            marker, color, dash, opacity = "arrow-import", "#6366f1", "", 0.55
        elif edge["type"] == "groups":
            marker, color, dash, opacity = "arrow-groups", "#7c3aed", 'stroke-dasharray="2,3"', 0.6
        else:  # calls
            marker, color, dash, opacity = "arrow-call", "#16a34a", 'stroke-dasharray="4,3"', 0.8
        x1, y1 = src.cx, src.cy
        x2, y2 = tgt.cx, tgt.cy
        return (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="1.4" {dash} opacity="{opacity}" '
            f'marker-end="url(#{marker})"/>'
        )


def render_svg(state: dict) -> str:
    return Renderer(state).render()
