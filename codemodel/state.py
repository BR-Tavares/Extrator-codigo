"""Persistência do estado (o JSON canônico entre extração e renderização).

Esse "state" é o equivalente ao manifest.json do dbt: um artefato JSON que
representa fielmente o código analisado e serve de entrada única para
qualquer etapa seguinte (aqui, o SVG; em outra ferramenta, poderia ser um
diagrama C4, um relatório, etc.). Nada é regenerado direto do código-fonte
na hora de renderizar — o state é a fonte de verdade daquele momento.
"""
from __future__ import annotations

import json
import os


def save_state(state: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=False)
    return path


def load_state(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
