"""Anulação de cadastro criado por engano (RF-1008, DDS §6.9, DD-89, DEC-61). A recepção ou a administração
pede; na aprovação, cada participante descarta o que é seu (documentos, presenças, alocações e trocas) na mesma
transação, e o paciente fica anulado, sem dado pessoal e com os números livres."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sar.modulo_01_acesso.contrato import AuditService, AutorizacaoService, PermissionGuard
from sar.modulo_08_dados.interfaces.pacientes import PacienteGravado, RepositorioPaciente
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado
from sar.nucleo.portas import Autorizacao, ImpactoAnulacao, ParticipanteAnulacao
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
ANULAR = "cadastro.paciente.anular"
NOMES_CONTAGEM = {
    "documentos": ("documento", "documentos"), "presencas": ("presença", "presenças"),
    "alocacoes": ("alocação", "alocações"), "trocas": ("troca", "trocas"),
}  # fmt: skip


def _vivo(uow: UnidadeDeTrabalho, paciente_id: int, travar: bool = False) -> PacienteGravado:
    paciente = uow.repositorio(RepositorioPaciente).por_id(paciente_id, travar=travar)
    if paciente is None or paciente.anulado_em is not None:
        raise NaoEncontrado()
    return paciente


def somar(uow: UnidadeDeTrabalho, participantes: Sequence[ParticipanteAnulacao], paciente_id: int) -> ImpactoAnulacao:
    contagens: dict[str, int] = {}
    sessao = mes = False
    for participante in participantes:
        impacto = participante.impacto(uow, paciente_id)
        for chave, quantidade in impacto.contagens.items():
            contagens[chave] = contagens.get(chave, 0) + quantidade
        sessao = sessao or impacto.alcanca_sessao_confirmada
        mes = mes or impacto.alcanca_mes_fechado
    return ImpactoAnulacao(contagens, sessao, mes)


def descrever_impacto(impacto: ImpactoAnulacao) -> str:
    """Texto da tela de decisão (§6.9): o que será descartado e se alcança sessão confirmada ou mês fechado."""
    partes = []
    for chave, quantidade in sorted(impacto.contagens.items()):
        if quantidade:
            singular, plural = NOMES_CONTAGEM.get(chave, (chave, chave))
            partes.append(f"{quantidade} {singular if quantidade == 1 else plural}")
    texto = f"Será descartado: {', '.join(partes)}." if partes else "Nada vinculado a descartar."
    if impacto.alcanca_sessao_confirmada:
        texto += " Alcança sessão já confirmada."
    if impacto.alcanca_mes_fechado:
        texto += " O mês fechado será marcado como alterado (RF-915)."
    return texto


class ExecutorAnularPaciente:
    """cadastro.paciente.anular: executa na aprovação, na transação dela (DEC-42)."""

    tipo = ANULAR

    def __init__(self, auditoria: AuditService, participantes: Sequence[ParticipanteAnulacao]) -> None:
        self._auditoria = auditoria
        self._participantes = participantes

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        paciente = uow.repositorio(RepositorioPaciente).por_id(int(parametros["paciente_id"]))
        if paciente is None or paciente.anulado_em is not None:
            return "Anular cadastro já anulado ou inexistente"
        impacto = descrever_impacto(somar(uow, self._participantes, paciente.id))
        return f"Anular o cadastro do prontuário {paciente.campos.prontuario} ({paciente.campos.nome}). {impacto}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        paciente = uow.repositorio(RepositorioPaciente).por_id(int(entidade_id))
        return paciente.versao if paciente is not None and paciente.anulado_em is None else None

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        paciente = _vivo(uow, int(parametros["paciente_id"]), travar=True)
        for participante in self._participantes:
            participante.descartar(uow, autor, paciente.id)
        uow.repositorio(RepositorioPaciente).anular(paciente.id, autor.instante)
        # Sem os valores apagados: eles já estão nos registros de criação e edição (DD-89).
        alteracoes = {"anulado": (False, True), "dados_pessoais": (True, False)}
        self._auditoria.registrar(
            uow, autor, ANULAR, "paciente", str(paciente.id), alteracoes, None, autorizacao.autorizador_id
        )


class ServicoAnulacao:
    """Implementa o AnulacaoService do contrato."""

    def __init__(
        self,
        executar: ExecutorDeOperacao,
        autorizacoes: AutorizacaoService,
        participantes: Sequence[ParticipanteAnulacao],
    ) -> None:
        self._executar = executar
        self._autorizacoes = autorizacoes
        self._participantes = participantes

    def impacto(self, contexto: Contexto, paciente_id: int) -> ImpactoAnulacao:
        if not (GUARDA.solicitavel(contexto, ANULAR) or GUARDA.pode(contexto, "acesso.autorizacao.decidir")):
            raise AcessoNegado()

        def operacao(uow: UnidadeDeTrabalho) -> ImpactoAnulacao:
            _vivo(uow, paciente_id)
            return somar(uow, self._participantes, paciente_id)

        return self._executar(operacao)

    def solicitar(self, contexto: Contexto, paciente_id: int, motivo: str) -> str:
        if not GUARDA.solicitavel(contexto, ANULAR):
            raise AcessoNegado()
        self._executar(lambda uow: _vivo(uow, paciente_id))
        return self._autorizacoes.solicitar(contexto, ANULAR, str(paciente_id), {"paciente_id": paciente_id}, motivo)
