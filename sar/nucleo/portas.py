"""Portas definidas pelo consumidor e implementadas pelo provedor (DD-02, DDS §3.4).

As implementações são ligadas só na raiz de composição (sar/composicao.py).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol

from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import UnidadeDeTrabalho


# ------------------------------------------------------------------ tempo e cifragem
class Relogio(Protocol):
    def agora(self) -> datetime:
        """Instante em UTC, com fuso."""
        ...

    def hoje(self) -> date:
        """Data local da clínica (America/Sao_Paulo)."""
        ...


class Finalidade(str, Enum):  # DD-07
    DOCUMENTOS = "documentos"
    RASCUNHOS = "rascunhos"
    QUARENTENA = "quarentena"
    CARGA = "carga"


class Cifra(Protocol):
    """AES-256-GCM com chave derivada por finalidade (HKDF-SHA256). O dado associado amarra o cifrado
    ao registro dono, impedindo troca de cifrados entre registros."""

    def cifrar(self, finalidade: Finalidade, dados: bytes, associado: bytes) -> tuple[bytes, bytes]:
        """Devolve (nonce, cifrado)."""
        ...

    def decifrar(self, finalidade: Finalidade, nonce: bytes, cifrado: bytes, associado: bytes) -> bytes: ...


# ------------------------------------------------------------------ MOD-01: autorização (DEC-42)
class ExecutorAutorizavel(Protocol):
    tipo: str  # código da operação, ex.: "cadastro.evento.corrigir"

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        """Texto para a tela de decisão da administração."""
        ...

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        """Versão do alvo, gravada na solicitação e conferida na aprovação (§5.3)."""
        ...

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizador_id: int, parametros: Mapping[str, Any]
    ) -> None:
        """Executa na mesma transação da aprovação; grava a marca de mês alterado se alcançar mês fechado."""
        ...


# ------------------------------------------------------------------ MOD-02: impedimentos e anulação
class OperacaoPeriodo(str, Enum):
    ENCERRAR = "encerrar"
    CORRIGIR_EVENTO = "corrigir_evento"


@dataclass(frozen=True, slots=True)
class Impedimento:
    codigo: str  # ex.: "presenca_posterior"
    descricao: str  # sem dado pessoal além do que o perfil já vê
    datas: Sequence[date] = field(default_factory=tuple)


class VerificadorImpedimento(Protocol):
    def impedimentos(
        self, uow: UnidadeDeTrabalho, paciente_id: int, data: date, operacao: OperacaoPeriodo
    ) -> list[Impedimento]: ...

    def ao_encerrar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int, data: date) -> None:
        """Efeitos automáticos do encerramento, na mesma transação (DD-31: cancela trocas e extras)."""
        ...


@dataclass(frozen=True, slots=True)
class ImpactoAnulacao:
    contagens: Mapping[str, int]  # ex.: {"presencas": 3, "documentos": 1}
    alcanca_sessao_confirmada: bool
    alcanca_mes_fechado: bool


class ParticipanteAnulacao(Protocol):
    def impacto(self, uow: UnidadeDeTrabalho, paciente_id: int) -> ImpactoAnulacao:
        """Mostrado à administração antes da decisão (§6.9)."""
        ...

    def descartar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int) -> None: ...


# ------------------------------------------------------------------ MOD-04: retenção (DD-01)
@dataclass(frozen=True, slots=True)
class MarcoRetencao:
    em_tratamento: bool
    ultimo_encerramento: date | None


class FonteMarcoRetencao(Protocol):
    def marco(self, uow: UnidadeDeTrabalho, paciente_id: int) -> MarcoRetencao: ...


# ------------------------------------------------------------------ MOD-02: CEP (AD-23)
@dataclass(frozen=True, slots=True)
class EnderecoCep:
    cep: str
    logradouro: str | None
    bairro: str | None
    municipio_ibge: str | None
    uf: str | None


class ProvedorCep(Protocol):
    """Único código que acessa a internet. Envia só o CEP (RNF-612)."""

    def consultar(self, cep: str) -> EnderecoCep | None:
        """None se o CEP não existe; IndisponivelExterno se o serviço não responde."""
        ...


# ------------------------------------------------------------------ MOD-07: pendências (DD-54)
class Prioridade(str, Enum):
    URGENCIA = "U"
    ALTA = "A"
    NORMAL = "N"


@dataclass(frozen=True, slots=True)
class ItemPendencia:
    codigo: str  # linha da matriz (§11.1)
    prioridade: Prioridade
    desde: datetime
    descricao: str
    destino: str  # rota para resolver
    paciente_id: int | None = None
    identificador_interno: str | None = None  # para o TI, no lugar de dado de paciente


class FontePendencia(Protocol):
    codigo: str

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int: ...

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]: ...

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        """Uma consulta para o conjunto, nunca uma por paciente (§11.3). Fontes sem paciente devolvem []."""
        ...
