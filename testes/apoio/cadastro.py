"""Apoio dos testes do cadastro: serviços montados com o banco de testes e dados da fábrica."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import Engine

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoAutorizacoes
from sar.modulo_02_cadastro.contrato import DadosPaciente
from sar.modulo_02_cadastro.eventos import ExecutorCorrigirEvento, ExecutorRemoverEvento, ServicoEventos
from sar.modulo_02_cadastro.servicos import ServicoContatos, ServicoLeituraCadastro, ServicoPacientes
from sar.modulo_06_configuracao.servicos import ServicoConfiguracao, ServicoReferencias
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.portas import VerificadorImpedimento
from sar.nucleo.uow import ExecutorDeOperacao
from testes.apoio.fabrica import Fabrica

AGORA = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)  # 10h em Jataí
INICIO = date(2026, 10, 1)
JATAI = "5211909"


@dataclass(frozen=True, slots=True)
class Cadastro:
    executar: ExecutorDeOperacao
    pacientes: ServicoPacientes
    contatos: ServicoContatos
    leitura: ServicoLeituraCadastro
    configuracao: ServicoConfiguracao
    autorizacoes: ServicoAutorizacoes
    eventos: ServicoEventos
    verificadores: list[VerificadorImpedimento] = field(default_factory=list)


def montar(engine: Engine) -> Cadastro:
    """Como o compor() monta; a lista de verificadores de impedimento começa vazia e o teste acrescenta."""
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    auditoria = ServicoAuditoria()
    verificadores: list[VerificadorImpedimento] = []
    executores = {
        e.tipo: e for e in (ExecutorCorrigirEvento(auditoria, verificadores), ExecutorRemoverEvento(auditoria))
    }
    autorizacoes = ServicoAutorizacoes(executar, auditoria, executores)
    return Cadastro(
        executar,
        ServicoPacientes(executar, auditoria, ServicoReferencias()),
        ServicoContatos(executar, auditoria),
        ServicoLeituraCadastro(),
        ServicoConfiguracao(executar, auditoria),
        autorizacoes,
        ServicoEventos(executar, auditoria, autorizacoes, verificadores),
        verificadores,
    )


def pessoa(usuarios: dict[str, int], chave: str = "recepcao", perfil: Perfil = Perfil.RECEPCAO) -> Contexto:
    return Contexto(usuarios.get(chave), perfil, None, "10.0.0.7", AGORA, "c" * 32)


def dados_completos(fabrica: Fabrica) -> DadosPaciente:
    """Paciente da fábrica com a tríade, CPF, CNS e residência em Goiás; o resto fica como pendência."""
    p = fabrica.paciente()
    return DadosPaciente(
        prontuario=p.prontuario,
        nome=p.nome,
        data_nascimento=p.data_nascimento,
        nome_mae=p.nome_mae,
        cpf=p.cpf,
        cns=p.cns,
        municipio=p.municipio.codigo_ibge,
    )
