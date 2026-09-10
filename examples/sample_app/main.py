"""Ponto de entrada do exemplo."""
import sys

from .service import criar_service


def executar():
    service = criar_service()
    total = service.criar_pedido("p1", [{"preco": 10.0, "quantidade": 2}])
    print(f"Total: {total}")
    print(service.consultar_pedido("p1"))


if __name__ == "__main__":
    sys.exit(executar() or 0)
