"""Termos assinados (DDS §7.8, §7.11; RF-805, RF-809, DD-28): consumidores dos eventos do MOD-04. DOC-03 liga-se à
troca pontual; DOC-07, ao paciente e ao mês em termo_extra. Rodam na transação de quem incorporou ou revinculou;
uma exceção aqui desfaria a incorporação inteira, por isso o documento que não serve só é registrado no log."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_03_operacao.contrato import PREFIXO_VINCULO_EXTRA, PREFIXO_VINCULO_TROCA
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.nucleo.contexto import Contexto
from sar.nucleo.documentos import DOCUMENTO_DA_EXTRA, DOCUMENTO_DA_TROCA
from sar.nucleo.eventos import DocumentoIncorporado, DocumentoRevinculado
from sar.nucleo.portas import Relogio
from sar.nucleo.uow import UnidadeDeTrabalho

log = logging.getLogger(__name__)
TERMO_TROCA = "operacao.troca.termo"
TERMO_EXTRA = "operacao.extra.termo"
_COMPETENCIA = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def manipulador_termos(
    relogio: Relogio, auditoria: AuditService
) -> Callable[[UnidadeDeTrabalho, DocumentoIncorporado], None]:
    def ligar(uow: UnidadeDeTrabalho, evento: DocumentoIncorporado) -> None:
        vinculo = evento.vinculo or ""
        if vinculo.startswith(PREFIXO_VINCULO_TROCA):
            _troca(uow, evento, vinculo.removeprefix(PREFIXO_VINCULO_TROCA))
        elif vinculo.startswith(PREFIXO_VINCULO_EXTRA):
            _extra(uow, evento, vinculo.removeprefix(PREFIXO_VINCULO_EXTRA))

    def _troca(uow: UnidadeDeTrabalho, evento: DocumentoIncorporado, numero: str) -> None:
        repositorio = uow.repositorio(RepositorioOperacao)
        troca = repositorio.troca_por_id(int(numero), travar=True) if numero.isdigit() else None
        if troca is None or troca.paciente_id != evento.paciente_id or troca.cancelada_em is not None:
            log.warning(TERMO_TROCA, extra={"resultado": "troca_de_outro_paciente_ou_cancelada"})
            return
        if evento.tipo != DOCUMENTO_DA_TROCA:
            log.warning(TERMO_TROCA, extra={"resultado": "tipo_nao_exigido"})
            return
        if troca.documento_id == evento.documento_id:
            return
        repositorio.ligar_documento_troca(troca.id, evento.documento_id)
        auditoria.registrar(
            uow, Contexto.sistema(TERMO_TROCA, relogio.agora()), TERMO_TROCA, "troca_pontual", str(troca.id),
            {"termo": (troca.documento_id is not None, True)},
        )  # fmt: skip

    def _extra(uow: UnidadeDeTrabalho, evento: DocumentoIncorporado, competencia: str) -> None:
        if not _COMPETENCIA.match(competencia) or evento.tipo != DOCUMENTO_DA_EXTRA:
            log.warning(TERMO_EXTRA, extra={"resultado": "vinculo_ou_tipo_invalido"})
            return
        repositorio = uow.repositorio(RepositorioOperacao)
        anterior = next(
            (d for p, c, d in repositorio.termos([evento.paciente_id]) if c == competencia), None
        )  # RF-805: um termo por paciente e mês; a nova versão substitui
        if anterior == evento.documento_id:
            return
        repositorio.gravar_termo(evento.paciente_id, competencia, evento.documento_id)
        auditoria.registrar(
            uow, Contexto.sistema(TERMO_EXTRA, relogio.agora()), TERMO_EXTRA, "paciente", str(evento.paciente_id),
            {"competencia": (None, competencia), "termo": (anterior is not None, True)},
        )  # fmt: skip

    return ligar


def manipulador_revinculo_termos(
    relogio: Relogio, auditoria: AuditService
) -> Callable[[UnidadeDeTrabalho, DocumentoRevinculado], None]:
    """Documento levado a outro paciente (RF-713): o termo deixa de valer para o anterior, e a pendência reaparece
    por derivação."""

    def desligar(uow: UnidadeDeTrabalho, evento: DocumentoRevinculado) -> None:
        repositorio = uow.repositorio(RepositorioOperacao)
        for troca in repositorio.trocas_do_documento(evento.documento_id):
            if troca.paciente_id != evento.paciente_anterior_id:
                continue
            repositorio.ligar_documento_troca(troca.id, None)
            auditoria.registrar(
                uow, Contexto.sistema(TERMO_TROCA, relogio.agora()), TERMO_TROCA, "troca_pontual", str(troca.id),
                {"termo": (True, False)},
            )  # fmt: skip
        for paciente_id, competencia in repositorio.remover_termos_do_documento(evento.documento_id):
            auditoria.registrar(
                uow, Contexto.sistema(TERMO_EXTRA, relogio.agora()), TERMO_EXTRA, "paciente", str(paciente_id),
                {"competencia": (competencia, None), "termo": (True, False)},
            )  # fmt: skip

    return desligar
