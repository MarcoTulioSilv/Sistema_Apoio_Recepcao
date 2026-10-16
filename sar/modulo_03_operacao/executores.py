"""Executores das operações do MOD-03 sujeitas à autorização (DDS §7.8, DEC-42). Cada um confere as regras de novo
na aprovação, executa na mesma transação e grava a marca de mês alterado se alcançar mês fechado (DD-26)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.calendario import competencia, competencias_entre
from sar.modulo_03_operacao.escalas import CANCELAR_REALIZADA, REABRIR, RETROATIVA, RegistroEscalas
from sar.modulo_03_operacao.frequencia import REFAZER, gravar_ligacoes, ligacoes_dos_parametros
from sar.modulo_03_operacao.marcas import gravar_marcas, meses_fechados
from sar.modulo_03_operacao.sessoes import ALTERAR_CONFIRMADA
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao, SessaoGravada
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import ConflitoDeVersao, NaoEncontrado, RegraViolada
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import Autorizacao, ExecutorAutorizavel
from sar.nucleo.uow import UnidadeDeTrabalho


def _sessao_da_chave(uow: UnidadeDeTrabalho, entidade_id: str) -> SessaoGravada | None:
    data, _, escala = entidade_id.partition(":")
    return uow.repositorio(RepositorioOperacao).sessao(date.fromisoformat(data), int(escala))


def _confirmada(uow: UnidadeDeTrabalho, data: date, escala_id: int) -> SessaoGravada:
    sessao = uow.repositorio(RepositorioOperacao).sessao(data, escala_id, travar=True)
    if sessao is None or sessao.confirmada_em is None:
        raise RegraViolada("sessao.nao_confirmada")
    return sessao


def _rotulo(uow: UnidadeDeTrabalho, data: date, escala_id: int) -> str:
    escala = dados.escalas(uow).get(escala_id)
    nome = f"{escala.rotulo.lower()} ({escala.codigo})" if escala else f"escala {escala_id}"
    return f"{data:%d/%m/%Y}, {nome}"


def _prontuario(uow: UnidadeDeTrabalho, leitura: LeituraCadastro, paciente_id: int) -> str:
    identificacao = leitura.identificacao(uow, paciente_id)
    return identificacao.prontuario if identificacao is not None else "?"


def _hoje(autor: Contexto) -> date:
    return autor.instante.astimezone(FUSO_CLINICA).date()


def _versao_da_sessao(uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
    sessao = _sessao_da_chave(uow, entidade_id)
    return sessao.versao if sessao is not None else None


class ExecutorReabrirSessao:
    """operacao.sessao.reabrir: desfaz a confirmação (ou a não realização); as presenças ficam como exceções."""

    tipo = REABRIR

    def __init__(self, auditoria: AuditService, parametros: LeitorParametros) -> None:
        self._auditoria = auditoria
        self._parametros = parametros

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        data, escala_id = date.fromisoformat(parametros["data"]), int(parametros["escala_id"])
        return f"Reabrir a sessão de {_rotulo(uow, data, escala_id)}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return _versao_da_sessao(uow, entidade_id)

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        data = date.fromisoformat(parametros["data"])
        sessao = _confirmada(uow, data, int(parametros["escala_id"]))
        fechados = meses_fechados(uow, dados.implantacao(self._parametros), [competencia(data)], autor)
        if not uow.repositorio(RepositorioOperacao).reabrir_sessao(sessao.id, sessao.versao):
            raise ConflitoDeVersao(None, None)
        self._auditoria.registrar(
            uow, autor, REABRIR, "sessao_turno", str(sessao.id), {"confirmada": (True, False)},
            autorizador_id=autorizacao.autorizador_id,
        )  # fmt: skip
        gravar_marcas(uow, fechados, autor, autorizacao)


class ExecutorAlterarPresencaConfirmada:
    """operacao.presenca.alterar_confirmada: muda a presença de um paciente, ou inclui quem ficou de fora."""

    tipo = ALTERAR_CONFIRMADA

    def __init__(self, auditoria: AuditService, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        situacao = "presente" if parametros["presente"] else "ausente"
        prontuario = _prontuario(uow, self._leitura, int(parametros["paciente_id"]))
        sessao = _rotulo(uow, date.fromisoformat(parametros["data"]), int(parametros["escala_id"]))
        return f"Registrar o prontuário {prontuario} como {situacao} na sessão confirmada de {sessao}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return _versao_da_sessao(uow, entidade_id)

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        data, paciente_id = date.fromisoformat(parametros["data"]), int(parametros["paciente_id"])
        presente = bool(parametros["presente"])
        sessao = _confirmada(uow, data, int(parametros["escala_id"]))
        repositorio = uow.repositorio(RepositorioOperacao)
        linha = next((p for p in repositorio.presencas_da_sessao(sessao.id) if p.paciente_id == paciente_id), None)
        antes = linha.situacao == "presente" if linha is not None else None
        if antes == presente:
            return
        if linha is None:
            if not presente:
                raise RegraViolada("paciente.fora_da_lista")
            obito = self._leitura.data_obito(uow, paciente_id)
            if obito is not None and data > obito:
                raise RegraViolada("INV-01")
            if self._leitura.periodo_aberto_em(uow, paciente_id, data) is None:
                raise RegraViolada("INV-04")
        fechados = meses_fechados(uow, dados.implantacao(self._parametros), [competencia(data)], autor)
        repositorio.gravar_presenca(sessao.id, paciente_id, "presente" if presente else "ausente")
        repositorio.tocar_sessao(sessao.id)
        self._auditoria.registrar(
            uow, autor, ALTERAR_CONFIRMADA, "sessao_turno", str(sessao.id),
            {"paciente_id": (None, paciente_id), "presente": (antes, presente)},
            autorizador_id=autorizacao.autorizador_id,
        )  # fmt: skip
        gravar_marcas(uow, fechados, autor, autorizacao)


class ExecutorAlocacaoRetroativa:
    """operacao.alocacao.registrar_retroativa: alocação que alcança sessão confirmada."""

    tipo = RETROATIVA

    def __init__(self, registro: RegistroEscalas, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._registro = registro
        self._leitura = leitura
        self._parametros = parametros

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        escala_id = parametros["escala_id"]
        escala = dados.escalas(uow).get(int(escala_id)) if escala_id is not None else None
        destino = f"na escala {escala.codigo}" if escala else "sem alocação"
        prontuario = _prontuario(uow, self._leitura, int(parametros["paciente_id"]))
        inicio = date.fromisoformat(parametros["inicio"])
        return f"Prontuário {prontuario} {destino} a partir de {inicio:%d/%m/%Y}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return None

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        inicio, hoje = date.fromisoformat(parametros["inicio"]), _hoje(autor)
        escala_id = int(parametros["escala_id"]) if parametros["escala_id"] is not None else None
        implantacao = dados.implantacao(self._parametros)
        fechados = set(meses_fechados(uow, implantacao, competencias_entre(inicio, hoje), autor))
        trecho = self._registro.gravar_alocacao(
            uow, autor, int(parametros["paciente_id"]), escala_id, inicio, autorizador_id=autorizacao.autorizador_id
        )
        if trecho is not None:
            alcancados = set(competencias_entre(trecho[0], min(trecho[1], hoje)))
            gravar_marcas(uow, sorted(fechados & alcancados), autor, autorizacao)


class ExecutorCancelarTrocaRealizada:
    """operacao.troca.cancelar_realizada: troca cuja origem ou destino já foi confirmado."""

    tipo = CANCELAR_REALIZADA

    def __init__(self, registro: RegistroEscalas, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._registro = registro
        self._leitura = leitura
        self._parametros = parametros

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        troca = uow.repositorio(RepositorioOperacao).troca_por_id(int(parametros["troca_id"]))
        if troca is None:
            return "Cancelar troca inexistente"
        prontuario = _prontuario(uow, self._leitura, troca.paciente_id)
        datas = f"de {troca.data_origem:%d/%m} para {troca.data_destino:%d/%m}"
        return f"Cancelar a troca do prontuário {prontuario}, {datas}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return None

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        troca = uow.repositorio(RepositorioOperacao).troca_por_id(int(parametros["troca_id"]))
        if troca is None:
            raise NaoEncontrado()
        fechados = meses_fechados(uow, dados.implantacao(self._parametros), [competencia(troca.data_origem)], autor)
        self._registro.gravar_cancelamento_troca(
            uow, autor, troca.id, autorizacao.motivo[:300], autorizador_id=autorizacao.autorizador_id
        )
        gravar_marcas(uow, fechados, autor, autorizacao)


class ExecutorRefazerPareamento:
    """operacao.pareamento.refazer em mês fechado."""

    tipo = REFAZER

    def __init__(self, auditoria: AuditService, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        prontuario = _prontuario(uow, self._leitura, int(parametros["paciente_id"]))
        return f"Refazer o pareamento do prontuário {prontuario} em {parametros['competencia']}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return None

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        comp = str(parametros["competencia"])
        fechados = meses_fechados(uow, dados.implantacao(self._parametros), [comp], autor)
        gravar_ligacoes(
            uow, self._auditoria, self._leitura, self._parametros, autor, int(parametros["paciente_id"]), comp,
            ligacoes_dos_parametros(parametros["ligacoes"]), autorizacao.autorizador_id,
        )  # fmt: skip
        gravar_marcas(uow, fechados, autor, autorizacao)


def executores(
    auditoria: AuditService, leitura: LeituraCadastro, parametros: LeitorParametros
) -> list[ExecutorAutorizavel]:
    """Os cinco da DDS §7.8, para a raiz de composição."""
    registro = RegistroEscalas(auditoria, leitura)
    return [
        ExecutorReabrirSessao(auditoria, parametros),
        ExecutorAlterarPresencaConfirmada(auditoria, leitura, parametros),
        ExecutorAlocacaoRetroativa(registro, leitura, parametros),
        ExecutorCancelarTrocaRealizada(registro, leitura, parametros),
        ExecutorRefazerPareamento(auditoria, leitura, parametros),
    ]
