"""Contrato do MOD-03 Operação (DDS §7.10): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import Protocol

from sar.nucleo.contexto import Contexto

DIAS_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")  # na ordem de date.weekday()
ROTULOS_TURNO = {1: "Primeiro turno", 2: "Segundo turno", 3: "Terceiro turno"}  # DD-75


@dataclass(frozen=True, slots=True)
class Escala:
    """Uma das seis escalas fixas (DEC-52, P-14)."""

    id: int
    codigo: str  # 1-seg, 1-ter…: só nas telas da enfermagem (DD-75)
    turno: int
    dias: frozenset[int]  # date.weekday(): 0 = segunda
    inicio: time
    fim: time

    @classmethod
    def de_texto(cls, id: int, codigo: str, turno: int, dias: str, inicio: time, fim: time) -> Escala:
        """`dias` como na tabela: "seg,qua,sex"."""
        return cls(id, codigo, turno, frozenset(DIAS_SEMANA.index(d) for d in dias.split(",")), inicio, fim)

    @property
    def rotulo(self) -> str:
        """Primeiro, segundo ou terceiro turno: o nome que a recepção vê (DD-75)."""
        return ROTULOS_TURNO[self.turno]

    def atende(self, data: date) -> bool:
        return data.weekday() in self.dias


class EstadoSessao(StrEnum):
    """Derivado do relógio, salvo confirmada e não realizada (§7.3, DD-23)."""

    FUTURA = "futura"
    EM_PREPARACAO = "em_preparacao"
    DEVIDA = "devida"
    CONFIRMACAO_LIBERADA = "confirmacao_liberada"
    URGENCIA = "urgencia"
    CONFIRMADA = "confirmada"
    NAO_REALIZADA = "nao_realizada"


class Origem(StrEnum):
    """Por que o paciente está na lista esperada da sessão (§7.2)."""

    ALOCADO = "alocado"
    TROCA_CHEGANDO = "troca_chegando"
    EXTRA_PLANEJADA = "extra_planejada"
    TROCA_SAINDO = "troca_saindo"  # pré-marcado como ausente (P-10)
    ACRESCENTADO = "acrescentado"  # pela recepção, vindo das presenças gravadas (DD-24)


class OrigemPar(StrEnum):
    """Prioridade do pareamento (§7.4): troca pontual, ligação manual, automático cronológico (RF-918)."""

    TROCA = "troca"
    MANUAL = "manual"
    AUTOMATICO = "automatico"


@dataclass(frozen=True, slots=True)
class ContagemEscalas:
    """RF-404, sem limite; os sem alocação aparecem explicitamente (RF-403)."""

    por_escala: Mapping[int, int]  # id da escala → pacientes alocados
    sem_alocacao: int


# ------------------------------------------------------------------ serviços para a interface
class EscalaService(Protocol):
    """Escalas da enfermagem (RF-401 a RF-406). Registrar e cancelar só pela enfermagem, auditado com o autor;
    `RequerAutorizacao` quando alcança sessão já confirmada."""

    def escalas(self, contexto: Contexto) -> list[Escala]: ...

    def contagem(self, contexto: Contexto, data: date) -> ContagemEscalas:
        """Pacientes com período aberto na data, pela alocação vigente."""
        ...

    def alocar(self, contexto: Contexto, paciente_id: int, escala_id: int | None, inicio: date) -> None:
        """Nova vigência a partir do início no período que cobre a data; None = sem alocação (DD-27). A mesma
        escala que já vale não grava nada. RegraViolada: "INV-03" (sem período na data), "INV-01" (depois do
        óbito), "escala.inexistente". RequerAutorizacao("operacao.alocacao.registrar_retroativa") se alguma sessão
        confirmada é afetada. NaoEncontrado (paciente)."""
        ...

    def alocar_em_lote(self, contexto: Contexto, alocacoes: Sequence[tuple[int, int | None]], inicio: date) -> None:
        """Vários pacientes de uma vez (RF-405), cada um na sua escala, numa transação. As RegraViolada do alocar
        trazem o paciente no detalhe ({"paciente_id": id})."""
        ...

    def registrar_troca(
        self, contexto: Contexto, paciente_id: int, origem: date, destino: date, escala_destino_id: int
    ) -> int:
        """Troca pontual (RF-503, P-10, P-11). RegraViolada: "P-11" (meses diferentes; a tela orienta a registrar
        ausência num mês e extra planejada no outro), "troca.origem_fora_da_escala", "troca.destino_na_propria_escala",
        "sessao.inexistente", "INV-04", "INV-01", "troca.origem_repetida". RequerAutorizacao("operacao.sessao.reabrir")
        se a origem ou o destino já foi confirmado."""
        ...

    def cancelar_troca(self, contexto: Contexto, troca_id: int, motivo: str | None = None) -> None:
        """RequerAutorizacao("operacao.troca.cancelar_realizada") se a origem ou o destino já foi confirmado.
        NaoEncontrado se não existe ou já foi cancelada."""
        ...

    def registrar_extra(self, contexto: Contexto, paciente_id: int, data: date, escala_id: int) -> int:
        """Extra planejada (RF-504). RegraViolada: "extra.na_propria_escala", "sessao.inexistente", "INV-04",
        "INV-01", "extra.repetida". RequerAutorizacao("operacao.sessao.reabrir") se a sessão já foi confirmada."""
        ...

    def cancelar_extra(self, contexto: Contexto, extra_id: int, motivo: str | None = None) -> None:
        """RequerAutorizacao("operacao.sessao.reabrir") se a sessão já foi confirmada. NaoEncontrado."""
        ...

    def solicitar_alocacao_retroativa(
        self, contexto: Contexto, paciente_id: int, escala_id: int | None, inicio: date, motivo: str
    ) -> str:
        """Pedido à administração quando o alocar pediu autorização; devolve o id da solicitação. As regras do
        alocar são conferidas no pedido e de novo na aprovação, que grava a marca se alcançar mês fechado."""
        ...

    def solicitar_cancelamento_troca(self, contexto: Contexto, troca_id: int, motivo: str) -> str:
        """Cancelar troca já realizada (origem ou destino confirmados), por autorização."""
        ...


# ------------------------------------------------------------------ sessão de turno (§7.3, DD-76)
LIMITE_EXTRAS = 4  # RN-01: aviso ao acrescentar com quatro extras no mês (RF-506); pendência a partir da quinta


@dataclass(frozen=True, slots=True)
class ResumoSessao:
    data: date
    escala: Escala
    estado: EstadoSessao


@dataclass(frozen=True, slots=True)
class PainelTurnos:
    """As sessões que pedem ação na tela inicial, da mais antiga para a mais nova (DD-76)."""

    implantacao_definida: bool  # vazia: nenhuma sessão é devida e a tela avisa o TI (DD-91)
    sessoes: tuple[ResumoSessao, ...]


@dataclass(frozen=True, slots=True)
class PacienteNaSessao:
    paciente_id: int
    nome: str
    prontuario: str
    origem: Origem
    presente: bool  # o padrão da origem, ou a marcação gravada
    marcado: bool  # há exceção gravada
    extras_no_mes: int  # provisórias (RF-506)

    @property
    def aviso_extra(self) -> bool:
        return self.extras_no_mes >= LIMITE_EXTRAS


@dataclass(frozen=True, slots=True)
class TelaTurno:
    data: date
    escala: Escala
    estado: EstadoSessao
    versao: int  # 0 enquanto a sessão não foi gravada; a confirmação devolve a que a tela leu (DD-17)
    pacientes: tuple[PacienteNaSessao, ...]  # em ordem de nome
    nao_realizada_motivo: str | None = None


@dataclass(frozen=True, slots=True)
class AusenciaDoMes:
    presenca_id: int | None  # a linha gravada; None na ausência ainda não gravada (troca saindo)
    data: date
    escala: Escala
    livre: bool  # ainda sem par


@dataclass(frozen=True, slots=True)
class FrequenciaAoAcrescentar:
    """O que a recepção vê ao acrescentar o paciente (RF-917, RF-506)."""

    ausencias: tuple[AusenciaDoMes, ...]
    extras_no_mes: int

    @property
    def aviso_extra(self) -> bool:
        return self.extras_no_mes >= LIMITE_EXTRAS


class SessaoTurnoService(Protocol):
    """O ciclo da sessão de turno na tela inicial (DD-23, DD-24, DD-30, DD-32, DD-76). Toda operação usa o
    instante do contexto. RegraViolada("implantacao.indefinida") com a data de implantação vazia (DD-91) e
    "sessao.inexistente" para data e escala sem sessão."""

    def painel(self, contexto: Contexto) -> PainelTurnos:
        """As de hoje em preparação, abertas, com confirmação liberada ou em urgência, e as de dias anteriores que
        ficaram sem confirmação."""
        ...

    def proximo_turno(self, contexto: Contexto) -> TelaTurno | None:
        """A sessão em preparação agora (RF-922), ou nada."""
        ...

    def tela_do_turno(self, contexto: Contexto, data: date, escala_id: int) -> TelaTurno: ...

    def marcar_ausencia(self, contexto: Contexto, data: date, escala_id: int, paciente_id: int) -> int:
        """Grava a exceção e devolve a nova versão da sessão. Antes do início, é a ausência avisada (P-13).
        RegraViolada: "sessao.fora_da_marcacao" (antes da preparação), "sessao.nao_realizada",
        "paciente.fora_da_lista". RequerAutorizacao("operacao.presenca.alterar_confirmada") se já confirmada."""
        ...

    def desmarcar(self, contexto: Contexto, data: date, escala_id: int, paciente_id: int) -> int:
        """Volta o paciente a presente; os mesmos erros do marcar."""
        ...

    def acrescentar_paciente(
        self, contexto: Contexto, data: date, escala_id: int, paciente_id: int, ausencia_id: int | None = None
    ) -> FrequenciaAoAcrescentar:
        """Paciente fora da lista, presente (DD-24); com ausencia_id, liga a presença a essa ausência (DD-25).
        RegraViolada: "INV-01", "INV-04", "paciente.ja_na_lista", "ligacao.invalida" e as do marcar. NaoEncontrado."""
        ...

    def retirar_acrescentado(self, contexto: Contexto, data: date, escala_id: int, paciente_id: int) -> int:
        """Desfaz o acréscimo feito por engano, antes da confirmação; devolve a nova versão."""
        ...

    def frequencia_ao_acrescentar(self, contexto: Contexto, paciente_id: int, data: date) -> FrequenciaAoAcrescentar:
        """As ausências do mês e as extras, para escolher a ausência a ligar antes de acrescentar (RF-917)."""
        ...

    def confirmar(self, contexto: Contexto, data: date, escala_id: int, versao: int) -> None:
        """Resolve a lista esperada e grava todas as presenças, numa transação, com a sessão travada (DD-24).
        ConflitoDeVersao se a sessão mudou depois da leitura. RegraViolada: "sessao.confirmacao_nao_liberada"
        (antes da última hora, DD-32), "sessao.confirmada", "sessao.nao_realizada"."""
        ...

    def registrar_nao_realizada(self, contexto: Contexto, data: date, escala_id: int, motivo: str) -> None:
        """Só a administração (P-12): a sessão sai das previstas e as exceções gravadas são descartadas.
        RegraViolada: "sessao.futura", "sessao.confirmada" (precisa reabrir antes), "motivo.obrigatorio"."""
        ...

    def devidas_nao_confirmadas(self, contexto: Contexto) -> list[ResumoSessao]:
        """Sessões já começadas e ainda não confirmadas, da mais antiga para a mais nova."""
        ...

    def solicitar_reabertura(self, contexto: Contexto, data: date, escala_id: int, motivo: str) -> str:
        """Reabrir sessão confirmada (ou não realizada), por autorização; as presenças ficam como exceções."""
        ...

    def solicitar_alteracao_confirmada(
        self, contexto: Contexto, data: date, escala_id: int, paciente_id: int, presente: bool, motivo: str
    ) -> str:
        """Mudar a presença de um paciente em sessão confirmada, ou incluir quem ficou de fora, por autorização."""
        ...


# ------------------------------------------------------------------ frequência do paciente (§7.4, §7.5)
@dataclass(frozen=True, slots=True)
class BalancoMes:
    """RF-916. Extras provisórias com o mês aberto, definitivas com o mês fechado."""

    competencia: str
    previstas: int
    realizadas: int
    ausencias_nao_compensadas: int
    reposicoes: int
    extras: int
    a_realizar: int  # sessões do mês que ainda não aconteceram
    provisorio: bool

    @property
    def extra_alem_do_limite(self) -> bool:
        return self.extras > LIMITE_EXTRAS  # RN-01: sinaliza, nunca bloqueia


@dataclass(frozen=True, slots=True)
class ItemFrequencia:
    data: date
    escala: Escala
    presenca_id: int | None  # a linha gravada, quando há


@dataclass(frozen=True, slots=True)
class ParDoMes:
    ausencia: ItemFrequencia
    presenca: ItemFrequencia
    origem: OrigemPar


@dataclass(frozen=True, slots=True)
class PareamentoDoMes:
    balanco: BalancoMes
    pares: tuple[ParDoMes, ...]
    ausencias_livres: tuple[ItemFrequencia, ...]
    extras: tuple[ItemFrequencia, ...]
    ligacoes_ignoradas: int  # deixaram de valer por alteração posterior (§7.4, item 6)
    mes_fechado: bool


class FrequenciaService(Protocol):
    def balanco(self, contexto: Contexto, paciente_id: int, competencia: str) -> BalancoMes: ...

    def pareamento_do_mes(self, contexto: Contexto, paciente_id: int, competencia: str) -> PareamentoDoMes:
        """Os pares com a origem de cada um (RF-918). NaoEncontrado."""
        ...

    def refazer(
        self, contexto: Contexto, paciente_id: int, competencia: str, ligacoes: Sequence[tuple[int, int]]
    ) -> None:
        """Troca as ligações manuais do paciente no mês pelas informadas, cada uma (ausência, presença) pelos ids
        das presenças gravadas; o automático refaz o resto. RegraViolada("ligacao.invalida").
        RequerAutorizacao("operacao.pareamento.refazer") em mês fechado."""
        ...

    def solicitar_refazer(
        self, contexto: Contexto, paciente_id: int, competencia: str, ligacoes: Sequence[tuple[int, int]], motivo: str
    ) -> str: ...

    def dar_ciencia(self, contexto: Contexto, presenca_id: int) -> None:
        """A enfermagem toma ciência da presença acrescentada pela recepção sem troca nem extra planejada (RF-921).
        RegraViolada: "ciencia.desnecessaria", "ciencia.ja_registrada". NaoEncontrado."""
        ...
