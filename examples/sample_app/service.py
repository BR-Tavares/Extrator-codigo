"""Camada de regras de negócio do exemplo."""
from .repository import PedidoRepository


class PedidoService:
    """Orquestra a criação e consulta de pedidos."""

    def __init__(self):
        self.repo = PedidoRepository()

    def criar_pedido(self, pedido_id, itens):
        total = self._calcular_total(itens)
        self.repo.salvar(pedido_id, {"itens": itens, "total": total})
        return total

    def consultar_pedido(self, pedido_id):
        return self.repo.buscar(pedido_id)

    def _calcular_total(self, itens):
        return sum(item["preco"] * item["quantidade"] for item in itens)


def criar_service():
    return PedidoService()
