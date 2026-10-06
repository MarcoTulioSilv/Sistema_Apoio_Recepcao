"""Hierarquia única de erros (DDS §3.5). Cada contrato documenta quais destes pode lançar."""
from __future__ import annotations

from datetime import datetime
from typing import Any


class ErroSAR(Exception):
    """Base. Mensagens de erro nunca contêm dado pessoal (RNF-624)."""


class AcessoNegado(ErroSAR):
    """Perfil ou recurso sem permissão. A tela mostra mensagem genérica."""


class NaoEncontrado(ErroSAR):
    """Identificador inexistente ou de cadastro anulado."""


class RegraViolada(ErroSAR):
    def __init__(self, codigo: str, detalhe: dict[str, Any] | None = None) -> None:
        super().__init__(codigo)
        self.codigo = codigo  # ex.: "INV-02", "P-03.minimo", "CPF.repetido"
        self.detalhe = detalhe or {}


class ConfirmacaoNecessaria(ErroSAR):
    """Alerta que exige decisão explícita; repetir a chamada com a confirmação."""

    def __init__(self, codigo: str, dados: dict[str, Any] | None = None) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.dados = dados or {}


class ConflitoDeVersao(ErroSAR):
    def __init__(self, alterado_por: int | None, alterado_em: datetime | None) -> None:
        super().__init__("conflito de versão")
        self.alterado_por = alterado_por
        self.alterado_em = alterado_em


class RequerAutorizacao(ErroSAR):
    """A operação só pode ser feita por solicitação à administração (DEC-42)."""

    def __init__(self, tipo: str) -> None:
        super().__init__(tipo)
        self.tipo = tipo


class IntegridadeViolada(ErroSAR):
    """Hash do documento não confere na leitura (DD-38)."""


class IndisponivelExterno(ErroSAR):
    """Serviço externo fora do ar; o fluxo segue sem ele (RNF-507)."""
