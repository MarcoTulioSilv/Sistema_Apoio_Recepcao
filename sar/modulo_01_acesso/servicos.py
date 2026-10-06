"""Serviços do MOD-01 (DDS §5)."""

from __future__ import annotations

from collections.abc import Mapping

from sar.modulo_08_dados.canonico import serializar_alteracoes
from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho

# Tamanhos das colunas da tabela auditoria (0001): estourar é erro de programação, não de usuário.
_LIMITES = {"operacao": 80, "entidade": 60, "entidade_id": 40, "motivo": 500, "origem": 45}


class ServicoAuditoria:
    def registrar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        operacao: str,
        entidade: str,
        entidade_id: str | None,
        alteracoes: Mapping[str, tuple[object, object]] | None = None,
        motivo: str | None = None,
        autorizador_id: int | None = None,
    ) -> None:
        textos = {
            "operacao": operacao,
            "entidade": entidade,
            "entidade_id": entidade_id,
            "motivo": motivo,
            "origem": contexto.origem,
        }
        for campo, valor in textos.items():
            if valor is not None and len(valor) > _LIMITES[campo]:
                raise ValueError(f"{campo} maior que {_LIMITES[campo]} caracteres")
        if not operacao or not entidade:
            raise ValueError("operação e entidade são obrigatórias")
        mudancas = {campo: par for campo, par in (alteracoes or {}).items() if par[0] != par[1]}  # DD-10
        serializar_alteracoes(mudancas)  # recusa agora, e não no commit, valor sem forma canônica
        uow.auditar(
            RegistroAuditoria(
                contexto=contexto,
                operacao=operacao,
                entidade=entidade,
                entidade_id=entidade_id,
                alteracoes=mudancas or None,
                motivo=motivo,
                autorizador_id=autorizador_id,
            )
        )
