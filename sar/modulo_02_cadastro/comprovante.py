"""Comprovante do evento (DDS §6.5, DEC-53, RF-607): consumidores dos eventos do MOD-04. Rodam na transação de
quem incorporou ou revinculou o documento; uma exceção aqui desfaria a incorporação inteira, por isso o
documento que não serve ao evento só é registrado no log, e a pendência continua."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_02_cadastro.contrato import PREFIXO_VINCULO_EVENTO
from sar.modulo_08_dados.interfaces.pacientes import PeriodoGravado, RepositorioPaciente
from sar.nucleo.contexto import Contexto
from sar.nucleo.documentos import DOCUMENTO_DO_EVENTO
from sar.nucleo.eventos import DocumentoIncorporado, DocumentoRevinculado
from sar.nucleo.portas import Relogio
from sar.nucleo.uow import UnidadeDeTrabalho

log = logging.getLogger(__name__)
OPERACAO = "cadastro.evento.comprovante"


def _periodo_do_vinculo(vinculo: str | None) -> int | None:
    if vinculo is None or not vinculo.startswith(PREFIXO_VINCULO_EVENTO):
        return None
    numero = vinculo.removeprefix(PREFIXO_VINCULO_EVENTO)
    return int(numero) if numero.isdigit() else None


def _gravar(uow: UnidadeDeTrabalho, periodo: PeriodoGravado, documento_id: bytes | None) -> None:
    """Só o comprovante muda; o resto do evento fica como está."""
    uow.repositorio(RepositorioPaciente).gravar_evento(
        periodo.id, periodo.evento_tipo, periodo.evento_data, periodo.evento_local, documento_id,
        periodo.evento_registrado_em,
    )  # fmt: skip


def manipulador_comprovante(
    relogio: Relogio, auditoria: AuditService
) -> Callable[[UnidadeDeTrabalho, DocumentoIncorporado], None]:
    """DocumentoIncorporado com vínculo de evento: confere paciente e tipo exigido e liga o documento ao evento.
    Documento novo do mesmo evento (nova versão) substitui o anterior."""

    def ligar(uow: UnidadeDeTrabalho, evento: DocumentoIncorporado) -> None:
        periodo_id = _periodo_do_vinculo(evento.vinculo)
        if periodo_id is None:
            return  # documento de outra origem: não é com o cadastro
        repositorio = uow.repositorio(RepositorioPaciente)
        periodo = repositorio.periodo(periodo_id)
        paciente = repositorio.por_id(evento.paciente_id, travar=True)
        if periodo is None or periodo.paciente_id != evento.paciente_id or paciente is None or paciente.anulado_em:
            log.warning(OPERACAO, extra={"resultado": "periodo_de_outro_paciente"})
            return
        if periodo.evento_tipo is None or DOCUMENTO_DO_EVENTO[periodo.evento_tipo] != evento.tipo:
            log.warning(OPERACAO, extra={"resultado": "tipo_nao_exigido"})  # o evento pode ter sido corrigido
            return
        if periodo.evento_documento_id == evento.documento_id:
            return
        _gravar(uow, periodo, evento.documento_id)
        auditoria.registrar(
            uow, Contexto.sistema(OPERACAO, relogio.agora()), OPERACAO, "periodo_tratamento", str(periodo.id),
            {"comprovante": (periodo.evento_documento_id is not None, True)},
        )  # fmt: skip

    return ligar


def manipulador_revinculo(
    relogio: Relogio, auditoria: AuditService
) -> Callable[[UnidadeDeTrabalho, DocumentoRevinculado], None]:
    """Documento levado a outro paciente (RF-713): se era o comprovante de um evento do anterior, o evento volta
    a ficar sem comprovante, e a pendência reaparece por derivação."""

    def desligar(uow: UnidadeDeTrabalho, evento: DocumentoRevinculado) -> None:
        repositorio = uow.repositorio(RepositorioPaciente)
        for periodo in repositorio.periodos(evento.paciente_anterior_id):
            if periodo.evento_documento_id != evento.documento_id:
                continue
            _gravar(uow, periodo, None)
            auditoria.registrar(
                uow, Contexto.sistema(OPERACAO, relogio.agora()), OPERACAO, "periodo_tratamento", str(periodo.id),
                {"comprovante": (True, False)},
            )  # fmt: skip

    return desligar
