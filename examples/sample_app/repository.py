"""Camada de acesso a dados do exemplo."""
import json


class PedidoRepository:
    """Guarda e recupera pedidos (versão de brinquedo, em memória)."""

    def __init__(self):
        self._dados = {}

    def salvar(self, pedido_id, payload):
        self._dados[pedido_id] = json.dumps(payload)

    def buscar(self, pedido_id):
        bruto = self._dados.get(pedido_id)
        return json.loads(bruto) if bruto else None
