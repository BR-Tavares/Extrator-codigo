"""Checagem do artefato renderizado — a etapa "Check" do pipeline do Archify.

O Archify descreve isso como: "artifact checks reject malformed geometry
and unsafe routes" antes de entregar o resultado. Aqui fazemos o
equivalente básico sobre as caixas já posicionadas pelo renderer: nenhuma
caixa com dimensão inválida, e módulos (o nível mais externo) não podem se
sobrepor — se isso acontecer, é bug no algoritmo de layout, não algo pra
entregar silenciosamente.
"""
from __future__ import annotations


def check_geometry(boxes: dict) -> list[str]:
    problems: list[str] = []

    for box in boxes.values():
        if box.w <= 0 or box.h <= 0:
            problems.append(f"'{box.id}': dimensão inválida (w={box.w:.1f}, h={box.h:.1f})")
        if box.x < 0 or box.y < 0:
            problems.append(f"'{box.id}': posição negativa (x={box.x:.1f}, y={box.y:.1f})")

    modules = [b for b in boxes.values() if b.kind in ("module", "source")]
    for i, a in enumerate(modules):
        for b in modules[i + 1:]:
            overlap = not (
                a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y
            )
            if overlap:
                problems.append(f"caixas de topo sobrepostas: '{a.id}' e '{b.id}'")

    return problems
