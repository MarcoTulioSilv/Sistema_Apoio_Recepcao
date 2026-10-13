"""Contrato do MOD-02 Cadastro (DDS §6.7): a única parte importável de fora do módulo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol

from sar.modulo_06_configuracao.contrato import Municipio
from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import UnidadeDeTrabalho


class Sexo(str, Enum):
    FEMININO = "F"
    MASCULINO = "M"


class TipoTelefone(str, Enum):
    CELULAR = "celular"
    FIXO = "fixo"
    RECADO = "recado"


class TipoEvento(str, Enum):
    OBITO = "obito"
    ALTA = "alta"
    TRANSFERENCIA = "transferencia"
    TRANSPLANTE = "transplante"
    DESISTENCIA = "desistencia"


class Situacao(str, Enum):  # §6.3, sempre derivada
    EM_CADASTRO = "em_cadastro"
    SEM_ALOCACAO = "sem_alocacao"
    ATIVO = "ativo"
    INATIVO = "inativo"
    FALECIDO = "falecido"


@dataclass(frozen=True, slots=True)
class DadosPaciente:
    """Campos da ficha (RF-101, RF-110, RF-111), na ordem da ficha de papel (RF-106). Só o nome e o prontuário
    são obrigatórios para criar (P-03); o que faltar vira pendência nomeada (RF-102). CPF, CNS e CEP podem vir
    com pontuação: as regras guardam só os dígitos."""

    prontuario: str | None = None
    nome: str | None = None
    data_nascimento: date | None = None
    sexo: Sexo | None = None
    nome_mae: str | None = None
    cpf: str | None = None
    cns: str | None = None
    rg: str | None = None
    rg_orgao: str | None = None
    naturalidade_municipio: str | None = None  # código IBGE
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    municipio: str | None = None  # código IBGE; residência só em Goiás
    cep: str | None = None


class TipoCobertura(str, Enum):  # RF-301
    SUS = "sus"
    CONVENIO = "convenio"


@dataclass(frozen=True, slots=True)
class DadosCobertura:
    """SUS ou convênio ativo, com a carteirinha só no convênio (RF-301)."""

    tipo: TipoCobertura
    convenio_id: int | None = None
    carteirinha: str | None = None


# ------------------------------------------------------------------ saídas
@dataclass(frozen=True, slots=True)
class Identificacao:
    """O que identifica o paciente em lista, busca e conferência (DDS §6.7)."""

    paciente_id: int
    nome: str
    prontuario: str
    data_nascimento: date | None
    nome_mae: str | None


@dataclass(frozen=True, slots=True)
class PeriodoRef:
    id: int
    inicio: date
    fim: date | None  # data do evento; None enquanto aberto


@dataclass(frozen=True, slots=True)
class CoberturaFicha:
    inicio: date
    ate: date | None  # véspera do início da seguinte (DD-70); None na vigente
    tipo: TipoCobertura
    convenio_nome: str | None
    convenio_ativo: bool | None
    carteirinha: str | None


@dataclass(frozen=True, slots=True)
class PeriodoFicha:
    id: int
    inicio: date
    evento_tipo: TipoEvento | None
    evento_data: date | None
    evento_local: str | None
    comprovante_anexado: bool
    coberturas: tuple[CoberturaFicha, ...]


@dataclass(frozen=True, slots=True)
class TelefoneFicha:
    id: int
    ddd: str
    numero: str
    tipo: TipoTelefone


@dataclass(frozen=True, slots=True)
class ContatoFicha:
    id: int
    nome: str
    parentesco: str | None
    telefones: tuple[TelefoneFicha, ...]


@dataclass(frozen=True, slots=True)
class Ficha:
    paciente_id: int
    versao: int
    dados: DadosPaciente
    cep_verificado: bool
    idade: int | None
    situacao: Situacao
    pendencias: tuple[str, ...]  # campos faltantes e CEP não verificado (RF-102, RF-109)
    residencia: Municipio | None
    naturalidade: Municipio | None
    periodos: tuple[PeriodoFicha, ...]  # em ordem de início
    telefones: tuple[TelefoneFicha, ...]  # só os do paciente (INV-12)
    contatos: tuple[ContatoFicha, ...]
    possiveis_duplicatas: tuple[Identificacao, ...]  # tríade coincidente ainda não descartada (INV-08)


# ------------------------------------------------------------------ serviços
class PacienteService(Protocol):
    def criar(
        self,
        contexto: Contexto,
        dados: DadosPaciente,
        inicio: date | None,
        confirmar_duplicidade: bool = False,
        cobertura: DadosCobertura | None = None,
    ) -> int:
        """Cria o paciente com o período aberto desde o início do tratamento (P-03) e, se informada, a cobertura
        vigente desde o mesmo dia. As RegraViolada da cobertura são as do registrar_cobertura.

        RegraViolada: mínimo da P-03 ("P-03.minimo", com os faltantes), campo inválido, residência fora de Goiás
        ("municipio.fora_de_goias"), município inexistente, prontuário, CPF ou CNS repetido ("prontuario.repetido",
        "cpf.repetido", "cns.repetido", com o paciente_id de quem já usa, quando conhecido).
        ConfirmacaoNecessaria("triade", {"candidatos": [ids]}): repetir com confirmar_duplicidade=True."""
        ...

    def atualizar(self, contexto: Contexto, paciente_id: int, versao: int, dados: DadosPaciente) -> int:
        """Devolve a nova versão. ConflitoDeVersao, NaoEncontrado (inclusive anulado) e as RegraViolada do criar,
        salvo o mínimo da data de início. A tríade que passa a coincidir não bloqueia: vira possível duplicidade
        na ficha e na lista de pendências."""
        ...

    def buscar(self, contexto: Contexto, termo: str) -> list[Identificacao]:
        """Pelo nome (contém, sem caixa e acento), ou pelo prontuário, CPF ou CNS exatos. Termo com menos de 2
        caracteres não busca. Anulados nunca aparecem."""
        ...

    def ver_ficha(self, contexto: Contexto, paciente_id: int) -> Ficha:
        """NaoEncontrado se não existir ou estiver anulado."""
        ...

    def abrir_periodo(
        self, contexto: Contexto, paciente_id: int, inicio: date, cobertura: DadosCobertura | None = None
    ) -> int:
        """Retorno do paciente (RF-605). RegraViolada: "INV-02" (já há período aberto), "INV-01" (falecido),
        "periodo.antes_do_fim_anterior", "inicio.antes_do_nascimento", "periodo.inicio_repetido". NaoEncontrado."""
        ...

    def registrar_cobertura(self, contexto: Contexto, periodo_id: int, cobertura: DadosCobertura, inicio: date) -> None:
        """Nova vigência no período; a anterior termina na véspera (DD-70, RF-302). RegraViolada: "INV-09" (início
        repetido), "cobertura.antes_do_periodo", "cobertura.depois_do_fim", "cobertura.convenio",
        "cobertura.sus_sem_convenio", "cobertura.convenio_inativo". NaoEncontrado (período, convênio ou paciente
        anulado)."""
        ...

    def descartar_duplicidade(self, contexto: Contexto, paciente_id: int, outro_id: int) -> None:
        """Encerra a possível duplicidade do par (INV-08). RegraViolada("duplicidade.sem_coincidencia") se a
        tríade dos dois não coincide."""
        ...


class EventoService(Protocol):
    """Eventos do paciente (RF-601 a RF-606). O registro é direto; correção e remoção só por autorização da
    administração (DEC-42), que aprova na hora quando é ela quem pede (P-01)."""

    def registrar(self, contexto: Contexto, paciente_id: int, tipo: TipoEvento, data: date, local: str | None) -> None:
        """Encerra o período aberto. RegraViolada: as regras do evento (§6.2) e "evento.impedimentos", com a
        lista de Impedimento no detalhe, quando outro módulo tem fato posterior à data (RF-604, DEC-65)."""
        ...

    def solicitar_correcao(
        self,
        contexto: Contexto,
        periodo_id: int,
        tipo: TipoEvento,
        data: date,
        local: str | None,
        motivo: str,
    ) -> str:
        """Id da solicitação. As regras são conferidas no pedido e de novo na aprovação."""
        ...

    def solicitar_remocao(self, contexto: Contexto, periodo_id: int, motivo: str) -> str:
        """Reabre o período. Só o evento do último período (INV-02)."""
        ...


class ContatoService(Protocol):
    """Contatos e telefones dentro do agregado do paciente (RF-201, RF-202, INV-12). Toda operação trava o
    paciente; NaoEncontrado se ele, o contato ou o telefone não existir, for de outro paciente ou o paciente
    estiver anulado. Auditadas."""

    def incluir_contato(self, contexto: Contexto, paciente_id: int, nome: str, parentesco: str | None) -> int: ...

    def alterar_contato(self, contexto: Contexto, contato_id: int, nome: str, parentesco: str | None) -> None: ...

    def remover_contato(self, contexto: Contexto, contato_id: int) -> None:
        """Os telefones do contato saem com ele."""
        ...

    def incluir_telefone(
        self,
        contexto: Contexto,
        paciente_id: int,
        ddd: str,
        numero: str,
        tipo: TipoTelefone,
        contato_id: int | None = None,
    ) -> int:
        """Do paciente, ou do contato informado (que precisa ser dele); nunca dos dois (INV-12).
        RegraViolada("telefone.repetido") se o mesmo dono já tem o número."""
        ...

    def alterar_telefone(self, contexto: Contexto, telefone_id: int, ddd: str, numero: str, tipo: TipoTelefone) -> None:
        """Número e tipo; o dono não muda."""
        ...

    def remover_telefone(self, contexto: Contexto, telefone_id: int) -> None: ...


class LeituraCadastro(Protocol):
    """Para os outros módulos, na unidade de trabalho deles (DDS §6.7). Paciente anulado não existe aqui."""

    def identificacao(self, uow: UnidadeDeTrabalho, paciente_id: int) -> Identificacao | None: ...

    def periodo_aberto_em(self, uow: UnidadeDeTrabalho, paciente_id: int, data: date) -> PeriodoRef | None:
        """O período que cobre a data: início até ela e evento, se houver, nela ou depois (INV-03, INV-04)."""
        ...

    def data_obito(self, uow: UnidadeDeTrabalho, paciente_id: int) -> date | None: ...

    def pacientes_com_periodo_aberto_em(self, uow: UnidadeDeTrabalho, data: date) -> list[int]: ...
