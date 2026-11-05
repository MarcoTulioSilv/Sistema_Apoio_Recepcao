"""Contrato do MOD-05 Emissão e relatórios (DDS §9.6): a única parte importável de fora do módulo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from sar.nucleo.contexto import Contexto


class Modelo(StrEnum):
    """Os modelos .docx (DEC-76): o valor é o código gravado em modelo_documento e emissao_documento."""

    CATETER = "DOC-02"
    TROCA = "DOC-03"
    ALIMENTOS = "DOC-04"
    EXTRA = "DOC-07"
    CRACHA = "CRACHA"

    @property
    def titulo(self) -> str:
        return _TITULOS[self]


_TITULOS = {
    Modelo.CATETER: "Termo de responsabilidade — implante de cateter",
    Modelo.TROCA: "Declaração de troca de turno",
    Modelo.ALIMENTOS: "Termo de responsabilidade — alimentos",
    Modelo.EXTRA: "Termo de necessidade de diálise extra",
    Modelo.CRACHA: "Crachá do paciente",
}


@dataclass(frozen=True, slots=True)
class Variavel:
    nome: str
    descricao: str
    imagem: bool = False


@dataclass(frozen=True, slots=True)
class Problema:
    """Um problema do modelo enviado (§9.2), para a tela explicar em linguagem simples."""

    codigo: str  # arquivo.tipo, arquivo.macro, xml.dtd, referencia.externa, variavel.desconhecida, fonte...
    detalhe: str | None = None  # o nome da variável, da fonte ou da estrutura


@dataclass(frozen=True, slots=True)
class VersaoModelo:
    versao: int  # 0: o modelo inicial embutido (DD-103)
    hash_sha256: str
    enviado_em: datetime | None  # None na versão 0
    enviado_por: int | None
    ativo: bool
    ativado_em: datetime | None


@dataclass(frozen=True, slots=True)
class ModeloResumo:
    modelo: Modelo
    versoes: tuple[VersaoModelo, ...]  # da mais nova à 0
    variaveis: tuple[Variavel, ...]  # a lista fechada, para a tela de envio

    @property
    def ativa(self) -> int:
        return next(v.versao for v in self.versoes if v.ativo)


@dataclass(frozen=True, slots=True)
class Envio:
    versao: int  # a versão gravada, ainda inativa
    avisos: tuple[Problema, ...]  # variável partida pelo Word: não impede, mas a tela mostra
    previa: bytes  # PDF com paciente fictício (DD-42)


class ModeloService(Protocol):
    """Só a administração (§4.5, P-22). Envio, ativação e reversão auditados com o hash do arquivo."""

    def listar(self, contexto: Contexto) -> list[ModeloResumo]: ...

    def baixar(self, contexto: Contexto, modelo: Modelo, versao: int | None = None) -> bytes:
        """O .docx da versão (a ativa, sem versão), para editar no Word. NaoEncontrado."""
        ...

    def enviar(self, contexto: Contexto, modelo: Modelo, arquivo: bytes) -> Envio:
        """Valida (§9.2), gera a prévia e grava a versão nova, inativa. RegraViolada("modelo.invalido") com
        `detalhe["problemas"]`: a lista de (código, detalhe). IndisponivelExterno se o conversor não responder."""
        ...

    def previa(self, contexto: Contexto, modelo: Modelo, versao: int) -> bytes:
        """O PDF da versão com o paciente fictício. NaoEncontrado."""
        ...

    def ativar(self, contexto: Contexto, modelo: Modelo, versao: int) -> None:
        """A partir daí, toda emissão usa essa versão; reverter é ativar uma anterior, inclusive a 0. Ativar a que
        já está ativa não grava nem audita. NaoEncontrado."""
        ...


class Documento(StrEnum):
    """Os documentos emitidos para um paciente (§9.1, DEC-76); o crachá tem operação própria."""

    FICHA = "DOC-01"
    CATETER = "DOC-02"
    TROCA = "DOC-03"
    ALIMENTOS = "DOC-04"
    EXTRA = "DOC-07"


@dataclass(frozen=True, slots=True)
class DocumentoEmitido:
    """Gerado de novo a cada emissão, do cadastro atual (RNF-903); entregue em memória, nunca guardado (DD-43)."""

    pdf: bytes
    nome_arquivo: str  # sem dado do paciente: código do documento e data


class EmissaoService(Protocol):
    def emitir(
        self,
        contexto: Contexto,
        documento: Documento,
        paciente_id: int,
        troca_id: int | None = None,
        confirmar_reemissao: bool = False,
    ) -> DocumentoEmitido:
        """Recepção e administração (§4.5). O DOC-03 sai de uma troca do paciente registrada e não cancelada
        (`troca_id`, RF-804). O DOC-07 avisa se já houve emissão no mês: ConfirmacaoNecessaria("extra.emitido_no_mes")
        até `confirmar_reemissao` (RF-805). NaoEncontrado (paciente ou troca), RegraViolada("instituicao.ausente")
        sem os dados institucionais (RF-802), IndisponivelExterno se o conversor não responder."""
        ...

    def emitir_cracha(self, contexto: Contexto, paciente_id: int) -> DocumentoEmitido:
        """RF-808. RegraViolada("cracha.sem_foto"): a tela orienta a capturar a foto."""
        ...

    def emitir_declaracao_titular(
        self, contexto: Contexto, paciente_id: int, recebida_em: date, paginas_documentos: int, referencia: str
    ) -> DocumentoEmitido:
        """A declaração que acompanha a cópia ao titular (RF-1009, DD-105), em leiaute fixo. Só a administração
        (titular.copia.gerar); registrada como emissão do modelo TITULAR com a referência da requisição."""
        ...


class Relatorio(StrEnum):
    """O catálogo da §9.3. Operacionais: recepção, administração, visualizador e enfermagem; gerenciais: administração
    e visualizador (§4.5, P-20, DEC-55)."""

    ENTRADAS = "entradas"
    CIDADE = "cidade"
    EVENTOS = "eventos"
    CONVENIO = "convenio"
    FREQUENCIA_MENSAL = "frequencia_mensal"
    BALANCO_MENSAL = "balanco_mensal"
    PREVIA = "previa"
    OCUPACAO = "ocupacao"
    FAIXA_ETARIA = "faixa_etaria"
    SEXO = "sexo"
    RECORTE_LIVRE = "recorte_livre"

    @property
    def operacional(self) -> bool:
        return self in _OPERACIONAIS

    @property
    def titulo(self) -> str:
        return _TITULOS_RELATORIO[self]

    @property
    def filtros(self) -> frozenset[str]:
        """Os filtros que o relatório pede (os demais são ignorados): periodo, data_referencia, competencia,
        tipo_evento, modo_convenio, paciente_id."""
        return _FILTROS[self]


_OPERACIONAIS = frozenset({Relatorio.FREQUENCIA_MENSAL, Relatorio.BALANCO_MENSAL, Relatorio.PREVIA,
                           Relatorio.OCUPACAO, Relatorio.RECORTE_LIVRE})  # fmt: skip
_TITULOS_RELATORIO = {
    Relatorio.ENTRADAS: "Entradas de pacientes por período",
    Relatorio.CIDADE: "Pacientes por cidade",
    Relatorio.EVENTOS: "Eventos por período",
    Relatorio.CONVENIO: "Pacientes por convênio",
    Relatorio.FREQUENCIA_MENSAL: "Frequência mensal",
    Relatorio.BALANCO_MENSAL: "Balanço mensal",
    Relatorio.PREVIA: "PRÉVIA — mês em aberto",
    Relatorio.OCUPACAO: "Ocupação por escala",
    Relatorio.FAIXA_ETARIA: "Pacientes por faixa etária",
    Relatorio.SEXO: "Pacientes por sexo",
    Relatorio.RECORTE_LIVRE: "Frequência em recorte livre",
}
_FILTROS = {
    Relatorio.ENTRADAS: frozenset({"periodo"}),
    Relatorio.CIDADE: frozenset({"data_referencia"}),
    Relatorio.EVENTOS: frozenset({"periodo", "tipo_evento"}),
    Relatorio.CONVENIO: frozenset({"modo_convenio", "data_referencia", "periodo"}),
    Relatorio.FREQUENCIA_MENSAL: frozenset({"competencia"}),
    Relatorio.BALANCO_MENSAL: frozenset({"competencia", "paciente_id"}),
    Relatorio.PREVIA: frozenset({"paciente_id"}),
    Relatorio.OCUPACAO: frozenset({"data_referencia"}),
    Relatorio.FAIXA_ETARIA: frozenset({"data_referencia"}),
    Relatorio.SEXO: frozenset({"data_referencia"}),
    Relatorio.RECORTE_LIVRE: frozenset({"periodo"}),
}


class ModoConvenio(StrEnum):
    """RF-905: a situação numa data, ou a cobertura vigente em algum momento do período."""

    SITUACAO = "situacao"
    PERIODO = "periodo"


@dataclass(frozen=True, slots=True)
class Filtros:
    inicio: date | None = None
    fim: date | None = None
    data_referencia: date | None = None
    competencia: str | None = None  # AAAA-MM
    tipo_evento: str | None = None  # TipoEvento do MOD-02; None: todos
    modo_convenio: ModoConvenio = ModoConvenio.SITUACAO
    paciente_id: int | None = None


@dataclass(frozen=True, slots=True)
class Coluna:
    titulo: str
    numerica: bool = False


@dataclass(frozen=True, slots=True)
class Marca:
    """Sinalização que sai na tela, no PDF e no XLSX (DD-44)."""

    tipo: str  # inicio_serie (RF-907), nao_confirmadas (RF-914), mes_alterado (RF-915), previa (DD-47)
    texto: str


@dataclass(frozen=True, slots=True)
class Tabela:
    """O modelo tabular único (DD-44): tela, PDF e XLSX são renderizações dele, com as mesmas colunas e marcas."""

    relatorio: Relatorio
    titulo: str
    filtros: tuple[tuple[str, str], ...]  # (rótulo, valor já formatado), na ordem de exibição
    colunas: tuple[Coluna, ...]
    linhas: tuple[tuple[str | int, ...], ...]
    marcas: tuple[Marca, ...]
    gerado_em: datetime
    codigo_integridade: str  # DD-86


@dataclass(frozen=True, slots=True)
class ArquivoRelatorio:
    conteudo: bytes
    nome_arquivo: str
    tipo_mime: str


class FormatoExportacao(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"


class RelatorioService(Protocol):
    def disponiveis(self, contexto: Contexto) -> list[Relatorio]:
        """Os relatórios que o perfil vê (§4.5)."""
        ...

    def gerar(self, contexto: Contexto, relatorio: Relatorio, filtros: Filtros) -> Tabela:
        """AcessoNegado conforme o perfil; RegraViolada("relatorio.filtro.<nome>") para filtro faltante ou inválido;
        RegraViolada("relatorio.mes_incompleto") no mensal com sessão pendente, com `detalhe["pendentes"]`: a lista de
        (data, turno) que falta (RF-913). Auditada com os filtros."""
        ...

    def exportar(
        self, contexto: Contexto, relatorio: Relatorio, filtros: Filtros, formato: FormatoExportacao
    ) -> ArquivoRelatorio:
        """Só a administração (§4.5). As mesmas colunas e marcas da tela (RF-912, DD-44); XLSX só com valores, texto
        como texto (DD-45). Auditada com o relatório, os filtros e o formato (RNF-607)."""
        ...

    def aniversariantes(self, contexto: Contexto, data: date) -> list[str]:
        """Os nomes dos pacientes em tratamento que fazem aniversário na data; só na tela inicial, não exportável
        (§10, RF-909). Sem registro na trilha (§4.5). AcessoNegado para quem não é recepção nem administração."""
        ...
