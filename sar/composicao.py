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
from sar.modulo_02_cadastro.anulacao import ExecutorAnularPaciente, ServicoAnulacao
from sar.modulo_02_cadastro.cep import provedor_padrao
from sar.modulo_02_cadastro.comprovante import manipulador_comprovante, manipulador_revinculo
from sar.modulo_02_cadastro.contrato import (
    AnulacaoService,
    CepService,
    ContatoService,
    EventoService,
    LeituraCadastro,
    PacienteService,
    RascunhoService,
)
from sar.modulo_02_cadastro.eventos import ExecutorCorrigirEvento, ExecutorRemoverEvento, ServicoEventos
from sar.modulo_02_cadastro.pendencias import FONTES as FONTES_CADASTRO
from sar.modulo_02_cadastro.pendencias import ServicoMarcoRetencao
from sar.modulo_02_cadastro.rascunhos import FonteRascunhoProximoDoDescarte, ServicoRascunhos
from sar.modulo_02_cadastro.servicos import ServicoCep, ServicoContatos, ServicoLeituraCadastro, ServicoPacientes
from sar.modulo_03_operacao.contrato import EscalaService, FrequenciaService, LeituraOperacao, SessaoTurnoService
from sar.modulo_03_operacao.escalas import ServicoEscalas
from sar.modulo_03_operacao.executores import executores as executores_operacao
from sar.modulo_03_operacao.frequencia import ServicoFrequencia
from sar.modulo_03_operacao.integracao import (
    AlocacaoDaFicha,
    ParticipanteAnulacaoOperacao,
    VerificadorImpedimentoOperacao,
    VerificadorUsoImplantacao,
)
from sar.modulo_03_operacao.leitura import ServicoLeituraOperacao
from sar.modulo_03_operacao.pendencias import fontes as fontes_operacao
from sar.modulo_03_operacao.sessoes import ServicoSessoes
from sar.modulo_03_operacao.termos import manipulador_revinculo_termos, manipulador_termos
from sar.modulo_05_emissao.contrato import RelatorioService
from sar.modulo_05_emissao.relatorios import ServicoRelatorios
from sar.modulo_06_configuracao.contrato import ConfiguracaoService, Referencias
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL, ServicoConfiguracao, ServicoReferencias
from sar.modulo_08_dados.cadeia import gravar_encadeado
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.interfaces.autorizacoes import RepositorioAutorizacao
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.modulo_08_dados.interfaces.pacientes import RepositorioPaciente
from sar.modulo_08_dados.interfaces.parametros import RepositorioParametro
from sar.modulo_08_dados.interfaces.rascunhos import RepositorioRascunho
from sar.modulo_08_dados.interfaces.referencias import RepositorioConvenio, RepositorioMunicipio
from sar.modulo_08_dados.interfaces.sessoes import RepositorioSessao
from sar.modulo_08_dados.interfaces.trilha import RepositorioExpurgo, RepositorioTrilha
from sar.modulo_08_dados.interfaces.usuarios import RepositorioUsuario
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_08_dados.repositorios.autorizacoes import RepositorioAutorizacaoSQL
from sar.modulo_08_dados.repositorios.operacao import RepositorioOperacaoSQL
from sar.modulo_08_dados.repositorios.pacientes import RepositorioPacienteSQL
from sar.modulo_08_dados.repositorios.parametros import RepositorioParametroSQL
from sar.modulo_08_dados.repositorios.rascunhos import RepositorioRascunhoSQL
from sar.modulo_08_dados.repositorios.referencias import RepositorioConvenioSQL, RepositorioMunicipioSQL
from sar.modulo_08_dados.repositorios.sessoes import RepositorioSessaoSQL
from sar.modulo_08_dados.repositorios.trilha import RepositorioExpurgoSQL, RepositorioTrilhaSQL
from sar.modulo_08_dados.repositorios.usuarios import RepositorioUsuarioSQL
from sar.modulo_08_dados.uow import ExecutorSQL, FabricaRepositorio, GravadorAuditoria, UnidadeDeTrabalhoSQL
from sar.nucleo.eventos import (
    Barramento,
    CadeiaDivergente,
    DocumentoIncorporado,
    DocumentoRevinculado,
    UsuarioInativado,
)
from sar.nucleo.parametros import LeitorParametros, VerificadorUso
from sar.nucleo.portas import (
    Cifra,
    ExecutorAutorizavel,
    FonteMarcoRetencao,
    FontePendencia,
    ParticipanteAnulacao,
    ProvedorCep,
    Relogio,
    VerificadorImpedimento,
)
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
    RepositorioRascunho: RepositorioRascunhoSQL,
    RepositorioOperacao: RepositorioOperacaoSQL,
}


def montar_barramento(relogio: Relogio) -> Barramento:
    """Consumidores dos eventos de domínio (DDS §3.11)."""
    barramento = Barramento()
    barramento.assinar(CadeiaDivergente, manipulador_aviso_integridade(relogio))
    barramento.assinar(UsuarioInativado, manipulador_encerrar_sessoes(relogio))
    auditoria = ServicoAuditoria()  # só registra na unidade de trabalho de quem publicou
    barramento.assinar(DocumentoIncorporado, manipulador_comprovante(relogio, auditoria))
    barramento.assinar(DocumentoRevinculado, manipulador_revinculo(relogio, auditoria))
    barramento.assinar(DocumentoIncorporado, manipulador_termos(relogio, auditoria))
    barramento.assinar(DocumentoRevinculado, manipulador_revinculo_termos(relogio, auditoria))
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
    contatos: ContatoService
    eventos: EventoService
    anulacao: AnulacaoService
    rascunhos: RascunhoService
    cep: CepService
    fontes_pendencia: tuple[FontePendencia, ...]
    marco_retencao: FonteMarcoRetencao
    leitura_cadastro: LeituraCadastro
    escalas: EscalaService
    turnos: SessaoTurnoService
    frequencia: FrequenciaService
    leitura_operacao: LeituraOperacao
    relatorios: RelatorioService


# Verificadores de uso dos parâmetros imutáveis (DD-51): a data de implantação trava na primeira sessão confirmada.
VERIFICADORES_USO: dict[str, VerificadorUso] = {v.parametro: v for v in (VerificadorUsoImplantacao(),)}

# Executores das operações sujeitas à autorização (DEC-42), por tipo, além dos que o compor() monta com as
# dependências de cada módulo. Um tipo registrado aqui prevalece (os testes da web põem um executor falso).
EXECUTORES_AUTORIZAVEIS: dict[str, ExecutorAutorizavel] = {}

# Quem tem fatos datados que impedem encerrar o período (DD-31, DD-74), além do MOD-03, que o compor() monta.
VERIFICADORES_IMPEDIMENTO: list[VerificadorImpedimento] = []

# Quem descarta o que está ligado ao cadastro anulado (§6.9, DD-74), além do MOD-03, que o compor() monta. O MOD-04
# entra no Incremento 4.
PARTICIPANTES_ANULACAO: list[ParticipanteAnulacao] = []


def compor(
    engine: Engine,
    chave_mestra: bytes,
    gravar_auditoria: GravadorAuditoria = gravar_encadeado,
    hasher: Hasher | None = None,
    provedor_cep: ProvedorCep | None = None,
    relogio: Relogio | None = None,
) -> Componentes:
    """O hasher só muda nos testes, que usam um custo menor; em produção é bcrypt com custo 12 (DD-83). O provedor
    de CEP também, para os testes nunca acessarem a internet; em produção é ViaCEP com BrasilAPI (DD-88). O relógio
    também: a tela inicial depende da hora, e o teste a fixa."""
    relogio = relogio or RelogioSistema()
    barramento = montar_barramento(relogio)
    executar = montar_executor(engine, barramento, gravar_auditoria)
    auditoria = ServicoAuditoria(executar)
    parametros = LeitorParametrosSQL(executar)
    hasher = hasher or Hasher()
    referencias = ServicoReferencias()
    cep = provedor_cep or provedor_padrao()
    leitura_cadastro = ServicoLeituraCadastro()
    verificadores = [*VERIFICADORES_IMPEDIMENTO, VerificadorImpedimentoOperacao(auditoria)]
    participantes = [
        *PARTICIPANTES_ANULACAO,
        ParticipanteAnulacaoOperacao(auditoria, leitura_cadastro, parametros, relogio),
    ]
    executores = dict(EXECUTORES_AUTORIZAVEIS)
    dos_modulos: list[ExecutorAutorizavel] = [
        ExecutorCorrigirEvento(auditoria, verificadores),
        ExecutorRemoverEvento(auditoria),
        ExecutorAnularPaciente(auditoria, participantes),
        *executores_operacao(auditoria, leitura_cadastro, parametros),
    ]
    for executor in dos_modulos:
        executores.setdefault(executor.tipo, executor)
    autorizacoes = ServicoAutorizacoes(executar, auditoria, executores)
    cifra = CifraAesGcm(chave_mestra)
    return Componentes(
        relogio=relogio,
        cifra=cifra,
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
        autorizacoes=autorizacoes,
        pacientes=ServicoPacientes(executar, auditoria, referencias, cep, AlocacaoDaFicha(leitura_cadastro)),
        contatos=ServicoContatos(executar, auditoria),
        eventos=ServicoEventos(executar, auditoria, autorizacoes, verificadores),
        anulacao=ServicoAnulacao(executar, autorizacoes, participantes),
        rascunhos=ServicoRascunhos(executar, auditoria, cifra, parametros),
        cep=ServicoCep(executar, referencias, cep),
        # DD-54: o MOD-07 agrega as fontes de todos os módulos
        fontes_pendencia=(
            *FONTES_CADASTRO,
            FonteRascunhoProximoDoDescarte(parametros),
            *fontes_operacao(leitura_cadastro, parametros),
        ),
        marco_retencao=ServicoMarcoRetencao(),
        leitura_cadastro=leitura_cadastro,
        escalas=ServicoEscalas(executar, auditoria, leitura_cadastro, parametros, autorizacoes),
        turnos=ServicoSessoes(executar, auditoria, leitura_cadastro, parametros, autorizacoes),
        frequencia=ServicoFrequencia(executar, auditoria, leitura_cadastro, parametros, autorizacoes),
        leitura_operacao=ServicoLeituraOperacao(leitura_cadastro, parametros),
        relatorios=ServicoRelatorios(executar, leitura_cadastro),
    )


def ids_dos_logins(executar: ExecutorDeOperacao, logins: list[str]) -> dict[str, int]:
    """Superusuários de desenvolvimento (DD-85): o id de cada login de SAR_SUPERUSUARIOS que existe. Quem chama
    decide o que fazer com os que faltaram."""

    def operacao(uow: UnidadeDeTrabalho) -> dict[str, int]:
        usuarios = uow.repositorio(RepositorioUsuario)
        encontrados = {login: usuarios.por_login(login) for login in logins}
        return {login: u.id for login, u in encontrados.items() if u is not None}

    return executar(operacao)
