"""Raiz de composição (DD-02, DDS §3.4): o único lugar que liga implementações às portas do núcleo.

A partir do Incremento 1, também registra aqui as assinaturas de eventos, os executores de portas, as
fontes de pendência e os jobs de cada módulo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import Engine

from sar.modulo_01_acesso.contrato import (
    AuditService,
    AuthService,
    AutorizacaoService,
    IntegridadeService,
    SessionManager,
    UsuarioService,
)
from sar.modulo_01_acesso.senhas import Hasher
from sar.modulo_01_acesso.servicos import (
    GerenciadorSessao,
    ServicoAuditoria,
    ServicoAutenticacao,
    ServicoAutorizacoes,
    ServicoIntegridade,
    ServicoUsuarios,
    manipulador_aviso_integridade,
    manipulador_encerrar_sessoes,
)
from sar.modulo_02_cadastro.contrato import LeituraCadastro, PacienteService
from sar.modulo_02_cadastro.servicos import ServicoLeituraCadastro, ServicoPacientes
from sar.modulo_06_configuracao.contrato import ConfiguracaoService, Referencias
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL, ServicoConfiguracao, ServicoReferencias
from sar.modulo_08_dados.cadeia import gravar_encadeado
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.interfaces.autorizacoes import RepositorioAutorizacao
from sar.modulo_08_dados.interfaces.pacientes import RepositorioPaciente
from sar.modulo_08_dados.interfaces.parametros import RepositorioParametro
from sar.modulo_08_dados.interfaces.referencias import RepositorioConvenio, RepositorioMunicipio
from sar.modulo_08_dados.interfaces.sessoes import RepositorioSessao
from sar.modulo_08_dados.interfaces.trilha import RepositorioExpurgo, RepositorioTrilha
from sar.modulo_08_dados.interfaces.usuarios import RepositorioUsuario
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_08_dados.repositorios.autorizacoes import RepositorioAutorizacaoSQL
from sar.modulo_08_dados.repositorios.pacientes import RepositorioPacienteSQL
from sar.modulo_08_dados.repositorios.parametros import RepositorioParametroSQL
from sar.modulo_08_dados.repositorios.referencias import RepositorioConvenioSQL, RepositorioMunicipioSQL
from sar.modulo_08_dados.repositorios.sessoes import RepositorioSessaoSQL
from sar.modulo_08_dados.repositorios.trilha import RepositorioExpurgoSQL, RepositorioTrilhaSQL
from sar.modulo_08_dados.repositorios.usuarios import RepositorioUsuarioSQL
from sar.modulo_08_dados.uow import ExecutorSQL, FabricaRepositorio, GravadorAuditoria, UnidadeDeTrabalhoSQL
from sar.nucleo.eventos import Barramento, CadeiaDivergente, UsuarioInativado
from sar.nucleo.parametros import LeitorParametros, VerificadorUso
from sar.nucleo.portas import Cifra, ExecutorAutorizavel, Relogio
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho


class Ambiente(str, Enum):
    DESENVOLVIMENTO = "desenvolvimento"
    PRODUCAO = "producao"


def ambiente_atual() -> Ambiente:
    """SAR_AMBIENTE; sem a variável, produção (DD-85): o que só existe em desenvolvimento nunca liga por
    esquecimento. Valor desconhecido é erro, não palpite."""
    valor = os.environ.get("SAR_AMBIENTE", Ambiente.PRODUCAO.value)
    try:
        return Ambiente(valor)
    except ValueError:
        raise RuntimeError("SAR_AMBIENTE deve ser 'desenvolvimento' ou 'producao'") from None


# Interface do repositório (sem SQLAlchemy, importável pelos módulos) → implementação SQL.
REPOSITORIOS: dict[type, FabricaRepositorio] = {
    RepositorioTrilha: RepositorioTrilhaSQL,
    RepositorioExpurgo: RepositorioExpurgoSQL,
    RepositorioParametro: RepositorioParametroSQL,
    RepositorioConvenio: RepositorioConvenioSQL,
    RepositorioMunicipio: RepositorioMunicipioSQL,
    RepositorioUsuario: RepositorioUsuarioSQL,
    RepositorioSessao: RepositorioSessaoSQL,
    RepositorioAutorizacao: RepositorioAutorizacaoSQL,
    RepositorioPaciente: RepositorioPacienteSQL,
}


def montar_barramento(relogio: Relogio) -> Barramento:
    """Consumidores dos eventos de domínio (DDS §3.11)."""
    barramento = Barramento()
    barramento.assinar(CadeiaDivergente, manipulador_aviso_integridade(relogio))
    barramento.assinar(UsuarioInativado, manipulador_encerrar_sessoes(relogio))
    return barramento


def montar_executor(
    engine: Engine, barramento: Barramento, gravar_auditoria: GravadorAuditoria = gravar_encadeado
) -> ExecutorSQL:
    """O gravador padrão é a cadeia encadeada (DD-03); outro gravador só nos testes de unidade, sem banco."""

    def nova_unidade() -> UnidadeDeTrabalhoSQL:
        return UnidadeDeTrabalhoSQL(engine, barramento, gravar_auditoria, REPOSITORIOS)

    return ExecutorSQL(nova_unidade)


def compor_auditoria(engine: Engine, engine_expurgo: Engine | None = None) -> ServicoAuditoria:
    """Só a trilha, sem a cifra: o que o worker e a linha de comando precisam para verificar e expurgar."""
    barramento = montar_barramento(RelogioSistema())
    expurgo = montar_executor(engine_expurgo, barramento) if engine_expurgo is not None else None
    return ServicoAuditoria(montar_executor(engine, barramento), expurgo)


@dataclass(frozen=True, slots=True)
class Componentes:
    relogio: Relogio
    cifra: Cifra
    barramento: Barramento
    executar: ExecutorDeOperacao
    auditoria: AuditService
    integridade: IntegridadeService
    parametros: LeitorParametros
    configuracao: ConfiguracaoService
    referencias: Referencias
    autenticacao: AuthService
    sessoes: SessionManager
    usuarios: UsuarioService
    autorizacoes: AutorizacaoService
    pacientes: PacienteService
    leitura_cadastro: LeituraCadastro


# Verificadores de uso dos parâmetros imutáveis (DD-51). A data de implantação ganha o seu com a sessão
# confirmada, no Incremento 3 (MOD-03); até lá não há sessão confirmada, e ela pode ser definida.
VERIFICADORES_USO: dict[str, VerificadorUso] = {}

# Executores das operações sujeitas à autorização (DEC-42), por tipo. Chegam com os módulos 02 a 04.
EXECUTORES_AUTORIZAVEIS: dict[str, ExecutorAutorizavel] = {}


def compor(
    engine: Engine,
    chave_mestra: bytes,
    gravar_auditoria: GravadorAuditoria = gravar_encadeado,
    hasher: Hasher | None = None,
) -> Componentes:
    """O hasher só muda nos testes, que usam um custo menor; em produção é bcrypt com custo 12 (DD-83)."""
    relogio = RelogioSistema()
    barramento = montar_barramento(relogio)
    executar = montar_executor(engine, barramento, gravar_auditoria)
    auditoria = ServicoAuditoria(executar)
    parametros = LeitorParametrosSQL(executar)
    hasher = hasher or Hasher()
    referencias = ServicoReferencias()
    return Componentes(
        relogio=relogio,
        cifra=CifraAesGcm(chave_mestra),
        barramento=barramento,
        executar=executar,
        auditoria=auditoria,
        integridade=ServicoIntegridade(executar, auditoria),
        parametros=parametros,
        configuracao=ServicoConfiguracao(executar, auditoria, VERIFICADORES_USO),
        referencias=referencias,
        autenticacao=ServicoAutenticacao(executar, auditoria, parametros, relogio, hasher),
        sessoes=GerenciadorSessao(executar, auditoria, parametros, relogio),
        usuarios=ServicoUsuarios(executar, auditoria, hasher),
        autorizacoes=ServicoAutorizacoes(executar, auditoria, EXECUTORES_AUTORIZAVEIS),
        pacientes=ServicoPacientes(executar, auditoria, referencias),
        leitura_cadastro=ServicoLeituraCadastro(),
    )


def ids_dos_logins(executar: ExecutorDeOperacao, logins: list[str]) -> dict[str, int]:
    """Superusuários de desenvolvimento (DD-85): o id de cada login de SAR_SUPERUSUARIOS que existe. Quem chama
    decide o que fazer com os que faltaram."""

    def operacao(uow: UnidadeDeTrabalho) -> dict[str, int]:
        usuarios = uow.repositorio(RepositorioUsuario)
        encontrados = {login: usuarios.por_login(login) for login in logins}
        return {login: u.id for login, u in encontrados.items() if u is not None}

    return executar(operacao)
