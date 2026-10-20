"""Operações do MOD-04 sujeitas à autorização (DDS §8.6, DEC-42) e o participante da anulação de cadastro (DEC-61).

O descarte destrói a chave do documento e remove o arquivo (DD-04): a linha fica como registro, com o hash, e o
documento deixa de ser legível também no backup, ao fim do horizonte de retenção do restic. A remoção do arquivo vem
depois do commit; se falhar, sobra um arquivo cifrado sem chave, que a varredura de órfãos não remove (tem linha) mas
ninguém mais decifra.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from typing import Any

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_04_documentos.armazenamento import Cofre, Quarentena
from sar.modulo_04_documentos.contrato import DESBLOQUEAR, DESCARTAR
from sar.modulo_04_documentos.ingestao import id_do_texto
from sar.modulo_04_documentos.retencao import prazo_do_documento
from sar.modulo_08_dados.interfaces.documentos import DocumentoGravado, EstadoIngestao, RepositorioDocumentos
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import NaoEncontrado, RegraViolada
from sar.nucleo.portas import Autorizacao, FonteMarcoRetencao, ImpactoAnulacao
from sar.nucleo.uow import UnidadeDeTrabalho

DESCARTAR_DO_PACIENTE = "documento.paciente.descartar"
INGESTOES_VIVAS: tuple[EstadoIngestao, ...] = ("aberta", "recebida", "em_processamento", "aguardando_conferencia")


def _documento(uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> DocumentoGravado:
    documento = uow.repositorio(RepositorioDocumentos).documento(id_do_texto(str(parametros["documento_id"])))
    if documento is None:
        raise NaoEncontrado()
    return documento


def _nome_tipo(uow: UnidadeDeTrabalho, documento: DocumentoGravado) -> str:
    tipo = uow.repositorio(RepositorioDocumentos).tipo(documento.tipo)
    return tipo.nome if tipo else documento.tipo


def _destruir(uow: UnidadeDeTrabalho, cofre: Cofre, documento: DocumentoGravado, contexto: Contexto) -> None:
    uow.repositorio(RepositorioDocumentos).descartar(documento.id, contexto.instante)
    uow.depois_do_commit(lambda: cofre.destruir(documento.arquivo))


class ExecutorDescartarDocumento:
    """documento.descartar_fim_retencao: só depois do prazo derivado (DD-01), conferido de novo na aprovação."""

    tipo = DESCARTAR

    def __init__(self, auditoria: AuditService, cofre: Cofre, marco: FonteMarcoRetencao) -> None:
        self._auditoria = auditoria
        self._cofre = cofre
        self._marco = marco

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        documento = _documento(uow, parametros)
        vence = prazo_do_documento(uow, self._marco, documento)
        quando = f", prazo de retenção vencido em {vence:%d/%m/%Y}" if vence else ""
        return f"Descartar {_nome_tipo(uow, documento)} (versão {documento.versao}){quando}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return None

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        documento = _documento(uow, parametros)
        if documento.descartado_em is not None:
            raise RegraViolada("documento.descartado")
        vence = prazo_do_documento(uow, self._marco, documento)
        if vence is None or vence > autor.instante.astimezone(FUSO_CLINICA).date():
            raise RegraViolada("retencao.vigente")  # INV-13: nunca antes do prazo
        _destruir(uow, self._cofre, documento, autor)
        self._auditoria.registrar(
            uow, autor, DESCARTAR, "documento", documento.id.hex(), {"descartado": (False, True)},
            motivo=autorizacao.motivo, autorizador_id=autorizacao.autorizador_id,
        )  # fmt: skip


class ExecutorDesbloquearDocumento:
    """documento.desbloquear: só o bloqueio por detecção no rescan, depois da revisão (P-19). Hash divergente não se
    desbloqueia: o TI restaura o arquivo do backup, e a conferência de hash tira o bloqueio sozinha."""

    tipo = DESBLOQUEAR

    def __init__(self, auditoria: AuditService) -> None:
        self._auditoria = auditoria

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        documento = _documento(uow, parametros)
        return f"Desbloquear {_nome_tipo(uow, documento)} (versão {documento.versao}) após revisão do antimalware"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return None

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        documento = _documento(uow, parametros)
        if documento.bloqueio_motivo != "rescan":
            raise RegraViolada("documento.desbloqueio")
        uow.repositorio(RepositorioDocumentos).desbloquear(documento.id)
        self._auditoria.registrar(
            uow, autor, DESBLOQUEAR, "documento", documento.id.hex(), {"bloqueio": ("rescan", None)},
            motivo=autorizacao.motivo, autorizador_id=autorizacao.autorizador_id,
        )  # fmt: skip


class ParticipanteAnulacaoDocumentos:
    """Anulação de cadastro (§6.9, DEC-61): mesmo mecanismo do descarte, para todos os documentos do paciente; as
    ingestões em andamento são canceladas e a quarentena delas, apagada."""

    def __init__(self, auditoria: AuditService, cofre: Cofre, quarentena: Quarentena) -> None:
        self._auditoria = auditoria
        self._cofre = cofre
        self._quarentena = quarentena

    def impacto(self, uow: UnidadeDeTrabalho, paciente_id: int) -> ImpactoAnulacao:
        vivos = [d for d in uow.repositorio(RepositorioDocumentos).do_paciente(paciente_id) if d.descartado_em is None]
        return ImpactoAnulacao({"documentos": len(vivos)} if vivos else {}, False, False)

    def descartar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int, autorizacao: Autorizacao) -> None:
        repo = uow.repositorio(RepositorioDocumentos)
        vivos = [d for d in repo.do_paciente(paciente_id) if d.descartado_em is None]
        for documento in vivos:
            _destruir(uow, self._cofre, documento, contexto)
        for ingestao in repo.ingestoes_do_paciente(paciente_id, INGESTOES_VIVAS):
            repo.salvar_ingestao(replace(ingestao, estado="cancelada", token_hash=None, campos_candidatos_cifrados=None,
                                         atualizada_em=contexto.instante))  # fmt: skip
            uow.depois_do_commit(partial(self._quarentena.apagar, ingestao.id))
        if vivos:
            self._auditoria.registrar(
                uow, contexto, DESCARTAR_DO_PACIENTE, "paciente", str(paciente_id), {"documentos": (len(vivos), 0)},
                autorizador_id=autorizacao.autorizador_id,
            )  # fmt: skip
