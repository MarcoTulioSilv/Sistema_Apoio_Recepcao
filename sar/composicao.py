"""Raiz de composição (DD-02, DDS §3.4): o único lugar que liga implementações às portas do núcleo.

A partir do Incremento 1, também registra aqui as assinaturas de eventos, os executores de portas, as
fontes de pendência e os jobs de cada módulo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
from sar.modulo_02_cadastro.pendencias import ServicoChecklist, ServicoMarcoRetencao
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
from sar.modulo_04_documentos.antimalware import Antimalware, Clamd
from sar.modulo_04_documentos.armazenamento import Cofre, Pastas, Quarentena
from sar.modulo_04_documentos.contrato import DocumentoService, IngestaoService, LeituraDocumentos
from sar.modulo_04_documentos.documentos import ServicoDocumentos
from sar.modulo_04_documentos.executores import (
    ExecutorDesbloquearDocumento,
    ExecutorDescartarDocumento,
    ParticipanteAnulacaoDocumentos,
)
from sar.modulo_04_documentos.ingestao import ServicoIngestao
from sar.modulo_04_documentos.leitura import ServicoLeituraDocumentos
from sar.modulo_04_documentos.pendencias import fontes as fontes_documentos
from sar.modulo_04_documentos.rotinas import RotinasDocumentos
from sar.modulo_04_documentos.worker import ProcessadorIngestoes
from sar.modulo_05_emissao.contrato import RelatorioService
from sar.modulo_05_emissao.relatorios import ServicoRelatorios
from sar.modulo_06_configuracao.contrato import ConfiguracaoService, Referencias
from sar.modulo_06_configuracao.servicos import LeitorParametrosSQL, ServicoConfiguracao, ServicoReferencias
from sar.modulo_08_dados.cadeia import gravar_encadeado
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.interfaces.autorizacoes import RepositorioAutorizacao
from sar.modulo_08_dados.interfaces.documentos import RepositorioDocumentos
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
from sar.modulo_08_dados.repositorios.documentos import RepositorioDocumentosSQL
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


RAIZ = Path(__file__).resolve().parent.parent


def pastas_do_ambiente() -> Pastas:
    """SAR_COFRE e SAR_QUARENTENA (DD-34, SEG-29). Em desenvolvimento, sem elas, ficam em armazenamento/ no projeto
    (ignorada pelo Git); em produção são obrigatórias, para o cofre nunca cair por engano fora do backup."""
    cofre, quarentena = os.environ.get("SAR_COFRE"), os.environ.get("SAR_QUARENTENA")
    if not cofre or not quarentena:
        if ambiente_atual() is not Ambiente.DESENVOLVIMENTO:
            raise RuntimeError("SAR_COFRE e SAR_QUARENTENA são obrigatórias fora do desenvolvimento (DD-34)")
        return Pastas(RAIZ / "armazenamento" / "cofre", RAIZ / "armazenamento" / "quarentena")
    return Pastas(Path(cofre), Path(quarentena))


def antimalware_do_ambiente(tempo: float = 60.0) -> Antimalware:
    """SAR_CLAMAV_HOST e SAR_CLAMAV_PORTA; padrão, o clamd do compose no loopback."""
    host, porta = os.environ.get("SAR_CLAMAV_HOST", "127.0.0.1"), int(os.environ.get("SAR_CLAMAV_PORTA", "3310"))
    return Clamd(host, porta, tempo)


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
    RepositorioDocumentos: RepositorioDocumentosSQL,
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
    ingestao: IngestaoService
    documentos: DocumentoService
    leitura_documentos: LeituraDocumentos


# Verificadores de uso dos parâmetros imutáveis (DD-51): a data de implantação trava na primeira sessão confirmada.
VERIFICADORES_USO: dict[str, VerificadorUso] = {v.parametro: v for v in (VerificadorUsoImplantacao(),)}

# Executores das operações sujeitas à autorização (DEC-42), por tipo, além dos que o compor() monta com as
# dependências de cada módulo. Um tipo registrado aqui prevalece (os testes da web põem um executor falso).
EXECUTORES_AUTORIZAVEIS: dict[str, ExecutorAutorizavel] = {}

# Quem tem fatos datados que impedem encerrar o período (DD-31, DD-74), além do MOD-03, que o compor() monta.
VERIFICADORES_IMPEDIMENTO: list[VerificadorImpedimento] = []

# Quem descarta o que está ligado ao cadastro anulado (§6.9, DD-74), além do MOD-03 e do MOD-04, que o compor() monta.
PARTICIPANTES_ANULACAO: list[ParticipanteAnulacao] = []


def compor(
    engine: Engine,
    chave_mestra: bytes,
    gravar_auditoria: GravadorAuditoria = gravar_encadeado,
    hasher: Hasher | None = None,
    provedor_cep: ProvedorCep | None = None,
    relogio: Relogio | None = None,
    pastas: Pastas | None = None,
    antimalware: Antimalware | None = None,
) -> Componentes:
    """O hasher só muda nos testes, que usam um custo menor; em produção é bcrypt com custo 12 (DD-83). O provedor
    de CEP também, para os testes nunca acessarem a internet; em produção é ViaCEP com BrasilAPI (DD-88). O relógio
    também: a tela inicial depende da hora, e o teste a fixa. As pastas do cofre e da quarentena vêm do ambiente
    (pastas_do_ambiente), e os testes passam as suas. O antimalware da web só responde à pendência 18 (DD-97), com
    tempo curto; os testes passam um falso."""
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
    cifra = CifraAesGcm(chave_mestra)
    pastas = pastas or pastas_do_ambiente()
    quarentena, cofre = Quarentena(pastas.quarentena, cifra), Cofre(pastas.cofre, cifra)
    marco_retencao = ServicoMarcoRetencao()
    participantes = [
        *PARTICIPANTES_ANULACAO,
        ParticipanteAnulacaoOperacao(auditoria, leitura_cadastro, parametros, relogio),
        ParticipanteAnulacaoDocumentos(auditoria, cofre, quarentena),
    ]
    executores = dict(EXECUTORES_AUTORIZAVEIS)
    dos_modulos: list[ExecutorAutorizavel] = [
        ExecutorCorrigirEvento(auditoria, verificadores),
        ExecutorRemoverEvento(auditoria),
        ExecutorAnularPaciente(auditoria, participantes),
        *executores_operacao(auditoria, leitura_cadastro, parametros),
        ExecutorDescartarDocumento(auditoria, cofre, marco_retencao),
        ExecutorDesbloquearDocumento(auditoria),
    ]
    for executor in dos_modulos:
        executores.setdefault(executor.tipo, executor)
    autorizacoes = ServicoAutorizacoes(executar, auditoria, executores)
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
            *fontes_documentos(
                ServicoChecklist(), marco_retencao, antimalware or antimalware_do_ambiente(2.0), parametros
            ),
        ),
        marco_retencao=marco_retencao,
        leitura_cadastro=leitura_cadastro,
        escalas=ServicoEscalas(executar, auditoria, leitura_cadastro, parametros, autorizacoes),
        turnos=ServicoSessoes(executar, auditoria, leitura_cadastro, parametros, autorizacoes),
        frequencia=ServicoFrequencia(executar, auditoria, leitura_cadastro, parametros, autorizacoes),
        leitura_operacao=ServicoLeituraOperacao(leitura_cadastro, parametros),
        relatorios=ServicoRelatorios(executar, leitura_cadastro),
        ingestao=ServicoIngestao(executar, auditoria, parametros, quarentena, cofre, cifra, relogio),
        documentos=ServicoDocumentos(executar, auditoria, cofre),
        leitura_documentos=ServicoLeituraDocumentos(executar, auditoria, cofre, marco_retencao),
    )


def compor_worker(
    engine: Engine,
    chave_mestra: bytes,
    pastas: Pastas,
    antimalware: Antimalware,
    relogio: Relogio | None = None,
) -> ProcessadorIngestoes:
    """O consumidor da fila de ingestão (DD-63), pelo usuário de banco do worker (DD-58)."""
    relogio = relogio or RelogioSistema()
    executar = montar_executor(engine, montar_barramento(relogio))
    cifra = CifraAesGcm(chave_mestra)
    return ProcessadorIngestoes(executar, ServicoAuditoria(executar), LeitorParametrosSQL(executar),
                                Quarentena(pastas.quarentena, cifra), antimalware, cifra, relogio)  # fmt: skip


def compor_rotinas(engine: Engine, chave_mestra: bytes, pastas: Pastas, antimalware: Antimalware) -> RotinasDocumentos:
    """Revarredura, conferência de hash e órfãos do acervo (DD-41, DD-37), pelo usuário de banco do worker."""
    relogio = RelogioSistema()
    executar = montar_executor(engine, montar_barramento(relogio))
    return RotinasDocumentos(executar, ServicoAuditoria(executar), Cofre(pastas.cofre, CifraAesGcm(chave_mestra)),
                             antimalware, relogio)  # fmt: skip


def ids_dos_logins(executar: ExecutorDeOperacao, logins: list[str]) -> dict[str, int]:
    """Superusuários de desenvolvimento (DD-85): o id de cada login de SAR_SUPERUSUARIOS que existe. Quem chama
    decide o que fazer com os que faltaram."""

    def operacao(uow: UnidadeDeTrabalho) -> dict[str, int]:
        usuarios = uow.repositorio(RepositorioUsuario)
        encontrados = {login: usuarios.por_login(login) for login in logins}
        return {login: u.id for login, u in encontrados.items() if u is not None}

    return executar(operacao)
