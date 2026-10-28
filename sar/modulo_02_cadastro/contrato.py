"""Contrato do MOD-02 Cadastro (DDS §6.7): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Literal, Protocol

from sar.modulo_06_configuracao.contrato import Municipio
from sar.nucleo.contexto import Contexto
from sar.nucleo.portas import ImpactoAnulacao
from sar.nucleo.uow import UnidadeDeTrabalho


class Sexo(str, Enum):
    FEMININO = "F"
    MASCULINO = "M"


# Parentesco do contato (RF-201): lista fechada (DD-102); o que vier fora dela é recusado.
PARENTESCOS = ("Cônjuge", "Filho ou filha", "Pai ou mãe", "Irmão ou irmã", "Outro parente", "Vizinho ou amigo")


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


PREFIXO_VINCULO_EVENTO = "evento:"


def vinculo_do_evento(periodo_id: int) -> str:
    """Vínculo opaco da ingestão aberta a partir do evento pendente (§6.5): o MOD-04 guarda sem interpretar e
    devolve no DocumentoIncorporado."""
    return f"{PREFIXO_VINCULO_EVENTO}{periodo_id}"


@dataclass(frozen=True, slots=True)
class DadosTelefone:
    ddd: str
    numero: str
    tipo: TipoTelefone


@dataclass(frozen=True, slots=True)
class DadosContato:
    nome: str
    parentesco: str | None
    telefones: tuple[DadosTelefone, ...] = ()


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
class PaginaPacientes:
    itens: tuple[Identificacao, ...]
    tem_mais: bool  # há outra página depois desta


@dataclass(frozen=True, slots=True)
class PeriodoRef:
    id: int
    inicio: date
    fim: date | None  # data do evento; None enquanto aberto
    obito: bool = False  # o evento que encerrou o período foi óbito (INV-01)


@dataclass(frozen=True, slots=True)
class CoberturaFicha:
    """A cobertura do período, valendo do início ao fim dele (DD-101)."""

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
    cobertura: CoberturaFicha | None


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
        telefones: Sequence[DadosTelefone] = (),
        contatos: Sequence[DadosContato] = (),
    ) -> int:
        """Cria o paciente com o período aberto desde o início do tratamento (P-03) e, se informados, a cobertura
        vigente desde o mesmo dia, os telefones e os contatos, tudo numa transação. As RegraViolada da cobertura são
        as do registrar_cobertura; as de telefone e contato trazem a posição no detalhe ({"telefone": i} ou
        {"contato": j, "telefone": k}) e incluem "telefone.repetido" no mesmo dono.

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

    def identificar(self, contexto: Contexto, paciente_ids: Sequence[int]) -> dict[int, Identificacao]:
        """Nome, prontuário, nascimento e mãe de pacientes já conhecidos pela tela (a fila da conferência), numa
        consulta só (§11.3). Como a lista de pacientes, não vai à trilha: não é busca. Anulados ficam de fora."""
        ...

    def buscar(self, contexto: Contexto, termo: str) -> list[Identificacao]:
        """Pelo nome (contém, sem caixa e acento), pelo começo do prontuário, ou pelo começo do CPF ou do CNS (a
        partir de 3 dígitos, com ou sem pontuação). Termo com menos de 2 caracteres não busca. Anulados nunca
        aparecem."""
        ...

    def listar(
        self,
        contexto: Contexto,
        termo: str = "",
        deslocamento: int = 0,
        limite: int = 30,
        registrar_na_trilha: bool = True,
    ) -> PaginaPacientes:
        """A lista da tela de pacientes, página a página, em ordem de nome. Termo com menos de 2 caracteres lista
        todos; com mais, filtra como o buscar. Auditada só a quantidade (DD-10), e só quando registrar_na_trilha:
        a tela registra a abertura e a busca confirmada, não cada filtragem nem cada página da rolagem (DD-90)."""
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

    def registrar_cobertura(self, contexto: Contexto, periodo_id: int, cobertura: DadosCobertura) -> None:
        """A cobertura do período aberto que ainda não tem (DD-101); trocar é encerrar o período e abrir outro.
        RegraViolada: "INV-09" (o período já tem), "cobertura.periodo_encerrado", "cobertura.convenio",
        "cobertura.sus_sem_convenio", "cobertura.convenio_inativo". NaoEncontrado (período, convênio ou paciente
        anulado)."""
        ...

    def conferir_documento(
        self, contexto: Contexto, campo: Literal["cpf", "cns"], valor: str, paciente_id: int | None = None
    ) -> int | None:
        """Conferência imediata na tela (DD-22): RegraViolada se o dígito não confere; devolve o id do paciente
        que já usa o número (outro que não o paciente_id), ou None. Vazio é aceito e devolve None."""
        ...

    def verificar_cep(self, contexto: Contexto, paciente_id: int) -> bool:
        """Resolução da pendência de CEP não verificado: consulta de novo e grava o resultado. RegraViolada
        ("cep.ausente"); IndisponivelExterno se as fontes continuam fora do ar."""
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


class AnulacaoService(Protocol):
    """Anulação de cadastro criado por engano (RF-1008, §6.9, DD-89), só por autorização da administração."""

    def impacto(self, contexto: Contexto, paciente_id: int) -> ImpactoAnulacao:
        """O que será descartado nos outros módulos, mostrado antes da decisão. Para quem pode pedir ou decidir."""
        ...

    def solicitar(self, contexto: Contexto, paciente_id: int, motivo: str) -> str:
        """Id da solicitação; aprovada na hora quando a administração pede (P-01). Na aprovação, tudo o que está
        ligado ao cadastro é descartado na mesma transação e os dados pessoais são apagados."""
        ...


@dataclass(frozen=True, slots=True)
class EnderecoSugerido:
    """O que a consulta do CEP devolve para preencher a ficha; a pessoa confere e completa."""

    cep: str
    logradouro: str | None
    bairro: str | None
    municipio: Municipio | None  # da tabela do IBGE; None se a fonte trouxe um município que ela não tem


class CepService(Protocol):
    def consultar(self, contexto: Contexto, cep: str) -> EnderecoSugerido | None:
        """Consulta individual, no preenchimento (AD-23). None se o CEP não existe; IndisponivelExterno se as duas
        fontes estão fora do ar, e a ficha segue sem ela (QAS-03). RegraViolada("cep.invalido")."""
        ...


@dataclass(frozen=True, slots=True)
class RascunhoSalvo:
    conteudo: dict[str, str]  # campos do formulário, como digitados
    atualizado_em: datetime
    descarte_em: date  # último salvamento mais o prazo (RF-920); derivado, nunca gravado


class RascunhoService(Protocol):
    """Rascunho do próprio usuário (§6.6, RF-919): um por pessoa, cifrado. Nenhuma regra do cadastro roda no
    rascunho; AcessoNegado para quem não é recepção nem administração, e para o contexto de sistema."""

    def salvar(self, contexto: Contexto, conteudo: Mapping[str, str]) -> RascunhoSalvo:
        """Cria ou substitui. Conteúdo igual ao gravado não grava nem audita. RegraViolada("rascunho.conteudo")
        acima dos limites."""
        ...

    def retomar(self, contexto: Contexto) -> RascunhoSalvo | None: ...

    def descartar(self, contexto: Contexto) -> None: ...


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

    def identificacoes(self, uow: UnidadeDeTrabalho, paciente_ids: Sequence[int]) -> dict[int, Identificacao]:
        """As de vários pacientes numa consulta só (§11.3); os anulados e os inexistentes ficam de fora."""
        ...

    def periodo_aberto_em(self, uow: UnidadeDeTrabalho, paciente_id: int, data: date) -> PeriodoRef | None:
        """O período que cobre a data: início até ela e evento, se houver, nela ou depois (INV-03, INV-04)."""
        ...

    def data_obito(self, uow: UnidadeDeTrabalho, paciente_id: int) -> date | None: ...

    def pacientes_com_periodo_aberto_em(self, uow: UnidadeDeTrabalho, data: date) -> list[int]: ...

    def aniversariantes(self, uow: UnidadeDeTrabalho, data: date) -> list[Identificacao]:
        """Em tratamento na data e nascidos nesse dia e mês, em ordem de nome (RF-909). Quem nasceu em 29/02 aparece
        em 28/02 nos anos que não são bissextos."""
        ...

    def periodos_de(self, uow: UnidadeDeTrabalho, paciente_ids: Sequence[int] | None) -> dict[int, list[PeriodoRef]]:
        """Períodos de cada paciente, em ordem de início, numa consulta só (§11.3); de todos com None."""
        ...
