"""Enums de pedidos (valores = tipos PostgreSQL en migración 006)."""

from enum import StrEnum


class MetodoPago(StrEnum):
    CARD = "card"
    TRANSFER = "transfer"


class EstadoPago(StrEnum):
    PENDIENTE = "pendiente"
    PAGADO = "pagado"
    FALLIDO = "fallido"
    REEMBOLSADO = "reembolsado"
    CANCELADO = "cancelado"


class EstadoEnvio(StrEnum):
    PENDIENTE = "pendiente"
    PREPARANDO = "preparando"
    ENVIADO = "enviado"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"
