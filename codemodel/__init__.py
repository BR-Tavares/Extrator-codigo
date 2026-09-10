"""codemodel — prova de conceito: código -> estado (JSON) -> diagrama (SVG).

Inspirado em dois padrões de repositórios de referência:
  - dbt: extrai um manifest.json (o "estado") a partir do código-fonte,
    representando nodes e suas dependências, antes de qualquer execução;
  - Archify: transforma um modelo estrutural em diagrama SVG.

Aqui a pipeline é: extractor.py (código -> state) -> state.py (persistência)
-> renderer.py (state -> SVG), orquestrados pela CLI em cli.py.
"""

__version__ = "0.1.0"
