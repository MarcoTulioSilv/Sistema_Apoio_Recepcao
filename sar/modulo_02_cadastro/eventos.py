"""Eventos do paciente (DDS §6.2, RF-601 a RF-606): registro direto; correção e remoção por autorização, pelos
executores registrados no MOD-01 (DEC-42). Fatos de outros módulos posteriores à data passam pela porta
VerificadorImpedimento (DD-31, DD-74)."""

from __future__ import annotations

import zlib
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sar.modulo_01_acesso.contrato import AuditService, AutorizacaoService, PermissionGuard
from sar.modulo_02_cadastro.contrato import TipoEvento
from sar.modulo_02_cadastro.regras import validar_evento
from sar.modulo_02_cadastro.servicos import hoje_na_clinica
from sar.modulo_08_dados.interfaces.pacientes import PacienteGravado, PeriodoGravado, RepositorioPaciente
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.portas import OperacaoPeriodo, VerificadorImpedimento
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
CORRIGIR = "cadastro.evento.corrigir"
REMOVER = "cadastro.evento.remover"
NOMES = {
    TipoEvento.OBITO: "Óbito", TipoEvento.ALTA: "Alta", TipoEvento.TRANSFERENCIA: "Transferência",
    TipoEvento.TRANSPLANTE: "Transplante", TipoEvento.DESISTENCIA: "Desistência",
}  # fmt: skip


# ------------------------------------------------------------------ apoio comum
def _paciente_do_periodo(uow: UnidadeDeTrabalho, periodo_id: int) -> tuple[PacienteGravado, PeriodoGravado]:
    """O período e o paciente dele, travado (agregado) e vivo; NaoEncontrado senão."""
    repositorio = uow.repositorio(RepositorioPaciente)
    periodo = repositorio.periodo(periodo_id)
    if periodo is None:
        raise NaoEncontrado()
    paciente = repositorio.por_id(periodo.paciente_id, travar=True)
    if paciente is None or paciente.anulado_em is not None:
        raise NaoEncontrado()
    return paciente, periodo


def _verificar_impedimentos(
    uow: UnidadeDeTrabalho,
    verificadores: Sequence[VerificadorImpedimento],
    paciente_id: int,
    data: date,
    operacao: OperacaoPeriodo,
) -> None:
    impedimentos = [i for v in verificadores for i in v.impedimentos(uow, paciente_id, data, operacao)]
    if impedimentos:
        raise RegraViolada("evento.impedimentos", {"impedimentos": impedimentos})


def _impressao(periodo: PeriodoGravado) -> int:
    """Versão do evento para a autorização (§5.3): o período não tem coluna de versão, então a solicitação grava
    uma impressão do evento, e a aprovação é invalidada se ele mudou desde o pedido."""
    texto = f"{periodo.evento_tipo}|{periodo.evento_data}|{periodo.evento_local}|{periodo.evento_documento_id!r}"
    return zlib.crc32(texto.encode())


def _evento_atual(periodo: PeriodoGravado) -> tuple[TipoEvento, date]:
    if periodo.evento_tipo is None or periodo.evento_data is None:
        raise RegraViolada("evento.inexistente")
    return TipoEvento(periodo.evento_tipo), periodo.evento_data


def _descrever(periodo: PeriodoGravado) -> str:
    if periodo.evento_tipo is None or periodo.evento_data is None:
        return "sem evento"
    return f"{NOMES[TipoEvento(periodo.evento_tipo)]} em {periodo.evento_data:%d/%m/%Y}"


def _versao(uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
    periodo = uow.repositorio(RepositorioPaciente).periodo(int(entidade_id))
    return _impressao(periodo) if periodo is not None else None


# ------------------------------------------------------------------ correção
def _validar_correcao(
    uow: UnidadeDeTrabalho,
    verificadores: Sequence[VerificadorImpedimento],
    periodo_id: int,
    tipo: TipoEvento,
    data: date,
    local: str | None,
    hoje: date,
) -> tuple[PacienteGravado, PeriodoGravado, str | None]:
    paciente, periodo = _paciente_do_periodo(uow, periodo_id)
    _, data_atual = _evento_atual(periodo)
    local_limpo = validar_evento(tipo, data, local, periodo.inicio, True, None, hoje)
    seguintes = [p for p in uow.repositorio(RepositorioPaciente).periodos(paciente.id) if p.inicio > periodo.inicio]
    if seguintes and tipo is TipoEvento.OBITO:
        raise RegraViolada("INV-01")  # há período depois: óbito aqui deixaria fatos posteriores a ele
    if seguintes and data > seguintes[0].inicio:
        raise RegraViolada("evento.depois_do_periodo_seguinte")
    if data < data_atual:  # antecipar o fim pode deixar fatos de outros módulos depois dele (DEC-65)
        _verificar_impedimentos(uow, verificadores, paciente.id, data, OperacaoPeriodo.CORRIGIR_EVENTO)
    return paciente, periodo, local_limpo


class ExecutorCorrigirEvento:
    """cadastro.evento.corrigir (RF-606): tipo, data e local. Trocar o tipo desliga o comprovante, que deixa de
    ser o exigido (DEC-53); a pendência volta por derivação."""

    tipo = CORRIGIR

    def __init__(self, auditoria: AuditService, verificadores: Sequence[VerificadorImpedimento]) -> None:
        self._auditoria = auditoria
        self._verificadores = verificadores

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        periodo = uow.repositorio(RepositorioPaciente).periodo(int(parametros["periodo_id"]))
        if periodo is None:
            return "Corrigir evento de período inexistente"
        paciente = uow.repositorio(RepositorioPaciente).por_id(periodo.paciente_id)
        prontuario = paciente.campos.prontuario if paciente else "?"
        novo = f"{NOMES[TipoEvento(parametros['tipo'])]} em {date.fromisoformat(parametros['data']):%d/%m/%Y}"
        return f"Corrigir evento do prontuário {prontuario}: {_descrever(periodo)} → {novo}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return _versao(uow, entidade_id)

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizador_id: int, parametros: Mapping[str, Any]
    ) -> None:
        tipo, data = TipoEvento(parametros["tipo"]), date.fromisoformat(parametros["data"])
        _, periodo, local = _validar_correcao(
            uow, self._verificadores, int(parametros["periodo_id"]), tipo, data, parametros.get("local"),
            hoje_na_clinica(autor),
        )  # fmt: skip
        documento = periodo.evento_documento_id if tipo.value == periodo.evento_tipo else None
        uow.repositorio(RepositorioPaciente).gravar_evento(
            periodo.id, tipo.value, data, local, documento, autor.instante
        )
        alteracoes = {
            "evento_tipo": (periodo.evento_tipo, tipo.value), "evento_data": (periodo.evento_data, data),
            "evento_local": (periodo.evento_local, local),
            "comprovante": (periodo.evento_documento_id is not None, documento is not None),
        }  # fmt: skip
        self._auditoria.registrar(
            uow, autor, CORRIGIR, "periodo_tratamento", str(periodo.id), alteracoes, None, autorizador_id
        )


# ------------------------------------------------------------------ remoção
def _validar_remocao(uow: UnidadeDeTrabalho, periodo_id: int) -> PeriodoGravado:
    paciente, periodo = _paciente_do_periodo(uow, periodo_id)
    _evento_atual(periodo)
    ultimo = uow.repositorio(RepositorioPaciente).periodos(paciente.id)[-1]
    if ultimo.id != periodo.id:
        raise RegraViolada("evento.nao_e_o_ultimo")  # reabrir este deixaria dois períodos abertos (INV-02)
    return periodo


class ExecutorRemoverEvento:
    """cadastro.evento.remover (RF-606): evento registrado por engano; o período volta a ficar aberto."""

    tipo = REMOVER

    def __init__(self, auditoria: AuditService) -> None:
        self._auditoria = auditoria

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        periodo = uow.repositorio(RepositorioPaciente).periodo(int(parametros["periodo_id"]))
        if periodo is None:
            return "Remover evento de período inexistente"
        paciente = uow.repositorio(RepositorioPaciente).por_id(periodo.paciente_id)
        prontuario = paciente.campos.prontuario if paciente else "?"
        return f"Remover o evento do prontuário {prontuario} ({_descrever(periodo)}) e reabrir o período"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return _versao(uow, entidade_id)

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizador_id: int, parametros: Mapping[str, Any]
    ) -> None:
        periodo = _validar_remocao(uow, int(parametros["periodo_id"]))
        uow.repositorio(RepositorioPaciente).gravar_evento(periodo.id, None, None, None, None, None)
        alteracoes = {
            "evento_tipo": (periodo.evento_tipo, None), "evento_data": (periodo.evento_data, None),
            "evento_local": (periodo.evento_local, None),
            "comprovante": (periodo.evento_documento_id is not None, False),
        }  # fmt: skip
        self._auditoria.registrar(
            uow, autor, REMOVER, "periodo_tratamento", str(periodo.id), alteracoes, None, autorizador_id
        )


# ------------------------------------------------------------------ serviço
class ServicoEventos:
    """Implementa o EventoService do contrato."""

    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        autorizacoes: AutorizacaoService,
        verificadores: Sequence[VerificadorImpedimento],
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._autorizacoes = autorizacoes
        self._verificadores = verificadores

    def registrar(self, contexto: Contexto, paciente_id: int, tipo: TipoEvento, data: date, local: str | None) -> None:
        GUARDA.exigir(contexto, "cadastro.evento.registrar")
        hoje = hoje_na_clinica(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            paciente = repositorio.por_id(paciente_id, travar=True)
            if paciente is None or paciente.anulado_em is not None:
                raise NaoEncontrado()
            periodos = repositorio.periodos(paciente_id)
            obito = next((p.evento_data for p in periodos if p.evento_tipo == TipoEvento.OBITO.value), None)
            aberto = next((p for p in periodos if p.evento_tipo is None), None)
            if aberto is None:
                raise RegraViolada("INV-01" if obito is not None else "evento.periodo_encerrado")
            local_limpo = validar_evento(tipo, data, local, aberto.inicio, True, obito, hoje)
            _verificar_impedimentos(uow, self._verificadores, paciente_id, data, OperacaoPeriodo.ENCERRAR)
            repositorio.gravar_evento(aberto.id, tipo.value, data, local_limpo, None, contexto.instante)
            for verificador in self._verificadores:
                verificador.ao_encerrar(uow, contexto, paciente_id, data)  # DD-31: cancela trocas e extras
            self._auditoria.registrar(
                uow, contexto, "cadastro.evento.registrar", "periodo_tratamento", str(aberto.id),
                {"evento_tipo": (None, tipo.value), "evento_data": (None, data), "evento_local": (None, local_limpo)},
            )  # fmt: skip

        self._executar(operacao)

    def solicitar_correcao(
        self,
        contexto: Contexto,
        periodo_id: int,
        tipo: TipoEvento,
        data: date,
        local: str | None,
        motivo: str,
    ) -> str:
        if not GUARDA.solicitavel(contexto, CORRIGIR):
            raise AcessoNegado()
        hoje = hoje_na_clinica(contexto)
        self._executar(lambda uow: _validar_correcao(uow, self._verificadores, periodo_id, tipo, data, local, hoje))
        parametros = {"periodo_id": periodo_id, "tipo": tipo.value, "data": data.isoformat(), "local": local}
        return self._autorizacoes.solicitar(contexto, CORRIGIR, str(periodo_id), parametros, motivo)

    def solicitar_remocao(self, contexto: Contexto, periodo_id: int, motivo: str) -> str:
        if not GUARDA.solicitavel(contexto, REMOVER):
            raise AcessoNegado()
        self._executar(lambda uow: _validar_remocao(uow, periodo_id))
        return self._autorizacoes.solicitar(contexto, REMOVER, str(periodo_id), {"periodo_id": periodo_id}, motivo)
