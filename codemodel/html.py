"""Empacota o SVG num HTML autocontido — a ideia central de entrega do
Archify: "the result is one HTML file [...] works in any browser without
dependencies", com alternância de tema claro/escuro.

Diferente do Archify de verdade (que gera um app interativo, com busca de
nodes e rastreio de rotas em JS), aqui a interatividade é só o toggle de
tema — o resto é deliberadamente estático, pra manter a POC pequena.

wrap_state_in_viewer() é o viewer interativo: embute o state.json como JSON
inline e usa Cytoscape.js (lido de _bundles/) para renderizar o grafo com
pan/zoom, busca, filtro por tipo, seletor +nome+ e painel de detalhes.
"""
from __future__ import annotations

import json
import os


# ---------------------------------------------------------------------- #
# Template 1 — SVG estático (comportamento original, mantido intacto)
# ---------------------------------------------------------------------- #
_TEMPLATE_SVG = """<!doctype html>
<html lang="pt-br" data-theme="light">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root[data-theme="light"] {{ --bg: #ffffff; --fg: #1e293b; --panel: #f8fafc; --border: #e2e8f0; }}
  :root[data-theme="dark"]  {{ --bg: #0f172a; --fg: #e2e8f0; --panel: #1e293b; --border: #334155; }}
  body {{
    margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
    font-family: Helvetica, Arial, sans-serif; transition: background 0.15s, color 0.15s;
  }}
  header {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border);
  }}
  h1 {{ font-size: 16px; margin: 0; }}
  .meta {{ font-size: 12px; opacity: 0.7; margin-top: 2px; }}
  button {{
    background: var(--panel); color: var(--fg); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer;
  }}
  .diagram-wrap {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px; overflow: auto;
  }}
  svg rect[fill="#ffffff"] {{ fill: var(--panel); }}
  svg text.header-text {{ fill: var(--fg) !important; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>{title}</h1>
    <div class="meta">{meta_line}</div>
  </div>
  <button id="theme-toggle" type="button">Alternar tema</button>
</header>
<div class="diagram-wrap">
{svg}
</div>
<script>
  document.getElementById("theme-toggle").addEventListener("click", function () {{
    var root = document.documentElement;
    var current = root.getAttribute("data-theme");
    root.setAttribute("data-theme", current === "dark" ? "light" : "dark");
  }});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------- #
# Template 2 — viewer interativo Cytoscape.js
# ---------------------------------------------------------------------- #
# O marcador __CYTOSCAPE_JS__ é substituído em tempo de execução pelo
# conteúdo do bundle lido do disco (codemodel/_bundles/cytoscape.min.js).
# O marcador __STATE_JSON__ é substituído pelo JSON do estado serializado.
# ---------------------------------------------------------------------- #
_TEMPLATE_VIEW = """\
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f8fafc; --fg: #1e293b; --card: #ffffff; --border: #e2e8f0;
  --muted: #64748b; --primary: #4338ca;
  --c-module: #eef2ff; --s-module: #4338ca;
  --c-class:  #ecfeff; --s-class:  #0e7490;
  --c-func:   #f0fdf4; --s-func:   #15803d;
  --c-method: #fefce8; --s-method: #a16207;
  --c-source: #fef2f2; --s-source: #b91c1c;
  --c-cap:    #f5f3ff; --s-cap:    #6d28d9;
  --c-dim:    #f1f5f9; --s-dim:    #cbd5e1;
}}
html[data-theme="dark"] {{
  --bg: #0f172a; --fg: #e2e8f0; --card: #1e293b; --border: #334155;
  --muted: #94a3b8; --primary: #818cf8;
  --c-module: #1e1b4b; --s-module: #818cf8;
  --c-class:  #082f49; --s-class:  #38bdf8;
  --c-func:   #052e16; --s-func:   #4ade80;
  --c-method: #1c1708; --s-method: #fbbf24;
  --c-source: #1f0808; --s-source: #f87171;
  --c-cap:    #1a0a3a; --s-cap:    #a78bfa;
  --c-dim:    #1e293b; --s-dim:    #475569;
}}
body {{
  font-family: Helvetica, Arial, sans-serif; font-size: 13px;
  background: var(--bg); color: var(--fg);
  display: flex; flex-direction: column; height: 100vh; overflow: hidden;
}}

/* ---- toolbar ---- */
#toolbar {{
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 12px; border-bottom: 1px solid var(--border);
  background: var(--card); flex-shrink: 0;
}}
#toolbar h1 {{ font-size: 14px; font-weight: 700; white-space: nowrap; }}
#toolbar .sep {{ width: 1px; height: 20px; background: var(--border); }}
#toolbar input, #toolbar select {{
  background: var(--bg); color: var(--fg); border: 1px solid var(--border);
  border-radius: 5px; padding: 4px 8px; font-size: 12px;
}}
#toolbar input {{ width: 160px; }}
#toolbar button {{
  background: var(--bg); color: var(--fg); border: 1px solid var(--border);
  border-radius: 5px; padding: 4px 10px; font-size: 12px; cursor: pointer;
  white-space: nowrap;
}}
#toolbar button:hover {{ background: var(--border); }}
.type-filters {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
.type-filters label {{
  display: flex; align-items: center; gap: 3px; font-size: 11px;
  cursor: pointer; user-select: none;
}}
.dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; }}

/* ---- main area ---- */
#main {{ display: flex; flex: 1; overflow: hidden; }}
#cy {{ flex: 1; background: var(--bg); }}

/* ---- detail panel ---- */
#panel {{
  width: 260px; border-left: 1px solid var(--border);
  background: var(--card); overflow-y: auto; flex-shrink: 0;
  display: flex; flex-direction: column;
}}
#panel-header {{
  padding: 10px 12px; border-bottom: 1px solid var(--border);
  font-weight: 600; font-size: 12px; color: var(--muted);
  text-transform: uppercase; letter-spacing: .05em;
}}
#panel-body {{ padding: 12px; flex: 1; }}
.pf {{ margin-bottom: 10px; }}
.pf-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 2px; }}
.pf-value {{ font-size: 12px; word-break: break-word; }}
.pf-value code {{ font-family: monospace; font-size: 11px; }}
.dep-list {{ list-style: none; padding: 0; }}
.dep-list li {{ font-size: 11px; font-family: monospace; padding: 1px 0; color: var(--muted); }}
#panel-empty {{ padding: 16px 12px; font-size: 12px; color: var(--muted); }}

/* ---- dimmed nodes ---- */
.cy-dimmed {{ opacity: 0.12; }}
</style>
</head>
<body data-theme="">
<div id="toolbar">
  <h1 id="tb-title">{title}</h1>
  <div class="sep"></div>
  <input id="search-input" type="search" placeholder="buscar node…" title="Filtra por nome ou id">
  <input id="selector-input" type="text" placeholder="+nome+" style="width:120px" title="Seletor estilo dbt: nome | +nome | nome+ | +nome+">
  <button id="reset-btn">Limpar</button>
  <div class="sep"></div>
  <div class="type-filters" id="type-filters"></div>
  <div class="sep"></div>
  <button id="fit-btn">Encaixar</button>
  <button id="png-btn">PNG ↓</button>
  <button id="theme-btn">Tema</button>
  <span id="meta-line" style="font-size:11px;color:var(--muted);margin-left:4px"></span>
</div>
<div id="main">
  <div id="cy"></div>
  <div id="panel">
    <div id="panel-header">Detalhes</div>
    <div id="panel-body">
      <div id="panel-empty">Clique em um node para ver detalhes.</div>
      <div id="panel-fields" style="display:none"></div>
    </div>
  </div>
</div>

<script>
// ---- Cytoscape.js bundle (embutido) ----
{cytoscape_js}
</script>
<script>
// ---- State.json embutido ----
const STATE = {state_json};

// ---- Cores por resource_type ----
const COLORS = {{
  module:     {{ bg: 'var(--c-module)', border: 'var(--s-module)' }},
  class:      {{ bg: 'var(--c-class)',  border: 'var(--s-class)'  }},
  function:   {{ bg: 'var(--c-func)',   border: 'var(--s-func)'   }},
  method:     {{ bg: 'var(--c-method)', border: 'var(--s-method)' }},
  source:     {{ bg: 'var(--c-source)', border: 'var(--s-source)' }},
  capability: {{ bg: 'var(--c-cap)',    border: 'var(--s-cap)'    }},
}};
const ALL_TYPES = Object.keys(COLORS);

// ---- Transforma state.json → elementos Cytoscape ----
function buildElements() {{
  const elems = [];

  // mapa: node_id → capability_id (de edges "groups")
  const capParent = {{}};
  for (const e of STATE.edges) {{
    if (e.type === 'groups') capParent[e.target] = e.source;
  }}

  // capabilities primeiro (compound nodes / contêineres)
  for (const [id, n] of Object.entries(STATE.nodes)) {{
    if (n.resource_type !== 'capability') continue;
    elems.push({{ data: {{
      id, label: n.name, type: 'capability',
      docstring: n.docstring || '',
      depends_on: n.depends_on || [],
    }} }});
  }}

  // demais nodes — herdam parent se agrupados por uma capability
  for (const [id, n] of Object.entries(STATE.nodes)) {{
    if (n.resource_type === 'capability') continue;
    const parent = capParent[id] || undefined;
    elems.push({{ data: {{
      id,
      label: n.resource_type === 'function' || n.resource_type === 'method'
             ? n.name + '()' : n.name,
      type: n.resource_type,
      file: n.file || '',
      lineStart: n.line_start,
      lineEnd: n.line_end,
      docstring: n.docstring || '',
      depends_on: n.depends_on || [],
      parent,       // undefined = sem pai; string = compound
    }} }});
  }}

  // arestas — apenas import e calls (contains e groups = estrutura visual)
  for (const e of STATE.edges) {{
    if (e.type === 'contains' || e.type === 'groups') continue;
    elems.push({{ data: {{
      source: e.source,
      target: e.target,
      edgeType: e.type,
    }} }});
  }}

  return elems;
}}

// ---- Inicializa Cytoscape ----
const cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: buildElements(),
  style: [
    // compound (capability)
    {{ selector: 'node[type="capability"]', style: {{
      'background-color': 'var(--c-cap)',
      'border-color': 'var(--s-cap)',
      'border-width': 2,
      'border-style': 'dashed',
      'label': 'data(label)',
      'text-valign': 'top',
      'text-halign': 'center',
      'font-size': 12,
      'font-weight': 700,
      'color': 'var(--s-cap)',
      'padding': '14px',
    }} }},
    // nodes normais
    {{ selector: 'node:not([type="capability"])', style: {{
      'background-color': 'ele => (COLORS[ele.data("type")] || COLORS.module).bg',
      'border-color':     'ele => (COLORS[ele.data("type")] || COLORS.module).border',
      'border-width': 1.5,
      'label': 'data(label)',
      'text-valign': 'center',
      'text-halign': 'center',
      'font-size': 11,
      'color': 'var(--fg)',
      'width': 'label',
      'height': 24,
      'padding': '6px',
      'shape': 'roundrectangle',
    }} }},
    // source: pílula vermelha
    {{ selector: 'node[type="source"]', style: {{
      'background-color': 'var(--c-source)',
      'border-color': 'var(--s-source)',
      'shape': 'ellipse',
      'height': 22,
    }} }},
    // method: menor, amarelo
    {{ selector: 'node[type="method"]', style: {{
      'font-size': 10,
      'background-color': 'var(--c-method)',
      'border-color': 'var(--s-method)',
    }} }},
    // edges import (azul-índigo, sólida)
    {{ selector: 'edge[edgeType="import"]', style: {{
      'line-color': '#6366f1',
      'target-arrow-color': '#6366f1',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.9,
      'width': 1.4,
      'opacity': 0.6,
      'curve-style': 'bezier',
    }} }},
    // edges calls (verde, tracejada)
    {{ selector: 'edge[edgeType="calls"]', style: {{
      'line-color': '#16a34a',
      'target-arrow-color': '#16a34a',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.8,
      'width': 1.2,
      'line-style': 'dashed',
      'line-dash-pattern': [5, 4],
      'opacity': 0.7,
      'curve-style': 'bezier',
    }} }},
    // node selecionado
    {{ selector: 'node:selected', style: {{
      'border-width': 3,
      'border-color': 'var(--primary)',
      'overlay-opacity': 0,
    }} }},
    // dimmed (busca / seletor)
    {{ selector: '.dimmed', style: {{
      'opacity': 0.12,
    }} }},
  ],
  layout: {{
    name: 'cose',
    animate: false,
    randomize: false,
    nodeRepulsion: 8000,
    idealEdgeLength: 80,
    edgeElasticity: 0.45,
    gravity: 0.8,
    numIter: 2500,
    tile: true,
    tilingPaddingVertical: 20,
    tilingPaddingHorizontal: 20,
    componentSpacing: 60,
  }},
  minZoom: 0.1,
  maxZoom: 4,
}});

// ---- Metadados na toolbar ----
const meta = STATE.metadata || {{}};
document.getElementById('meta-line').textContent =
  `${{meta.project || ''}}  ·  ${{meta.node_count || '?'}} nodes  ·  ${{meta.edge_count || '?'}} edges`;

// ---- Filtros de tipo (checkboxes) ----
const typeFiltersEl = document.getElementById('type-filters');
const visibleTypes = new Set(ALL_TYPES);

ALL_TYPES.forEach(t => {{
  const col = (COLORS[t] || COLORS.module).border;
  const label = document.createElement('label');
  label.innerHTML =
    `<input type="checkbox" checked data-type="${{t}}">` +
    `<span class="dot" style="background:${{col}};border:1px solid ${{col}}"></span>` +
    t;
  label.querySelector('input').addEventListener('change', e => {{
    if (e.target.checked) visibleTypes.add(t); else visibleTypes.delete(t);
    applyVisibility();
  }});
  typeFiltersEl.appendChild(label);
}});

function applyVisibility() {{
  cy.nodes().forEach(n => {{
    if (!visibleTypes.has(n.data('type'))) n.addClass('dimmed');
    else n.removeClass('dimmed');
  }});
}}

// ---- Painel de detalhes ----
const panelEmpty = document.getElementById('panel-empty');
const panelFields = document.getElementById('panel-fields');

function showPanel(node) {{
  const d = node.data();
  panelEmpty.style.display = 'none';
  panelFields.style.display = 'block';
  const rows = [
    ['id', `<code>${{d.id}}</code>`],
    ['tipo', d.type],
    ['arquivo', d.file ? `<code>${{d.file}}${{d.lineStart ? ':' + d.lineStart : ''}}</code>` : '—'],
    ['docstring', d.docstring || '—'],
    ['depends_on', d.depends_on && d.depends_on.length
      ? `<ul class="dep-list">${{d.depends_on.map(x => `<li>${{x}}</li>`).join('')}}</ul>`
      : '—'],
  ];
  panelFields.innerHTML = rows.map(([l, v]) =>
    `<div class="pf"><div class="pf-label">${{l}}</div><div class="pf-value">${{v}}</div></div>`
  ).join('');
}}

function clearPanel() {{
  panelEmpty.style.display = '';
  panelFields.style.display = 'none';
}}

cy.on('tap', 'node', e => showPanel(e.target));
cy.on('tap', e => {{ if (e.target === cy) clearPanel(); }});

// ---- Busca por nome / id ----
document.getElementById('search-input').addEventListener('input', e => {{
  const q = e.target.value.trim().toLowerCase();
  if (!q) {{ cy.elements().removeClass('dimmed'); return; }}
  cy.nodes().forEach(n => {{
    const match = n.data('label').toLowerCase().includes(q) ||
                  n.data('id').toLowerCase().includes(q);
    if (match) n.removeClass('dimmed'); else n.addClass('dimmed');
  }});
  cy.edges().addClass('dimmed');
}});

// ---- Seletor +nome+ (reimplementa selector.py em JS usando parent_map/child_map) ----
document.getElementById('selector-input').addEventListener('change', e => {{
  const expr = e.target.value.trim();
  if (!expr) {{ cy.elements().removeClass('dimmed'); return; }}
  applySelector(expr);
}});

function applySelector(expr) {{
  const upstream   = expr.startsWith('+');
  const downstream = expr.endsWith('+');
  const core = expr.replace(/^\+|\+$/g, '').toLowerCase();

  const parentMap = STATE.parent_map || {{}};
  const childMap  = STATE.child_map  || {{}};

  // seed: nodes cujo label ou id contém core
  const seed = new Set();
  cy.nodes().forEach(n => {{
    if (n.data('label').toLowerCase().includes(core) ||
        n.data('id').toLowerCase().includes(core)) seed.add(n.data('id'));
  }});

  if (!seed.size) return;

  const keep = new Set(seed);

  if (upstream) {{
    const stack = [...seed];
    while (stack.length) {{
      const cur = stack.pop();
      for (const p of (parentMap[cur] || [])) {{
        if (!keep.has(p)) {{ keep.add(p); stack.push(p); }}
      }}
    }}
  }}
  if (downstream) {{
    const stack = [...seed];
    while (stack.length) {{
      const cur = stack.pop();
      for (const c of (childMap[cur] || [])) {{
        if (!keep.has(c)) {{ keep.add(c); stack.push(c); }}
      }}
    }}
  }}

  cy.elements().addClass('dimmed');
  cy.nodes().forEach(n => {{ if (keep.has(n.data('id'))) n.removeClass('dimmed'); }});
  cy.edges().forEach(e => {{
    if (keep.has(e.data('source')) && keep.has(e.data('target'))) e.removeClass('dimmed');
  }});
}}

// ---- Botões ----
document.getElementById('reset-btn').addEventListener('click', () => {{
  cy.elements().removeClass('dimmed');
  document.getElementById('search-input').value = '';
  document.getElementById('selector-input').value = '';
  document.querySelectorAll('#type-filters input').forEach(i => {{ i.checked = true; }});
  visibleTypes.clear(); ALL_TYPES.forEach(t => visibleTypes.add(t));
}});

document.getElementById('fit-btn').addEventListener('click', () => cy.fit(undefined, 30));

document.getElementById('png-btn').addEventListener('click', () => {{
  const a = document.createElement('a');
  a.href = cy.png({{ scale: 2, bg: getComputedStyle(document.body).getPropertyValue('--bg') }});
  a.download = 'codemodel.png';
  a.click();
}});

document.getElementById('theme-btn').addEventListener('click', () => {{
  const html = document.documentElement;
  html.setAttribute('data-theme', html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
}});

// tema inicial: segue o sistema
if (window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.setAttribute('data-theme', 'dark');
else
  document.documentElement.setAttribute('data-theme', 'light');
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------- #
# Funções públicas
# ---------------------------------------------------------------------- #
def wrap_svg_in_html(svg: str, title: str, meta_line: str) -> str:
    """Template original — SVG estático com toggle de tema."""
    return _TEMPLATE_SVG.format(title=title, meta_line=meta_line, svg=svg)


def wrap_state_in_viewer(state: dict, title: str) -> str:
    """Viewer interativo: embute state.json + Cytoscape.js no HTML."""
    state_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    cytoscape_js = _read_bundle("cytoscape.min.js")
    return _TEMPLATE_VIEW.format(
        title=title,
        state_json=state_json,
        cytoscape_js=cytoscape_js,
    )


def _read_bundle(filename: str) -> str:
    """Lê um arquivo de _bundles/ relativo a este módulo."""
    bundle_dir = os.path.join(os.path.dirname(__file__), "_bundles")
    path = os.path.join(bundle_dir, filename)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
