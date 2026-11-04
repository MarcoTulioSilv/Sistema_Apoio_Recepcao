"""Contrato do MOD-11 Atendimento ao titular (DDS §15, RF-1009): a única parte importável de fora do módulo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from sar.nucleo.contexto import Contexto


class TipoRequisicao(StrEnum):
    """LGPD, art. 18 (§15)."""

    CONFIRMACAO_ACESSO = "confirmacao_acesso"
    CORRECAO = "correcao"
    INFORMACAO = "informacao"
    ELIMINACAO = "eliminacao"
    OUTROS = "outros"


class SituacaoRequisicao(StrEnum):
    ABERTA = "aberta"
    ATENDIDA = "atendida"
    NEGADA = "negada"


class Canal(StrEnum):
    """Por onde o pedido chegou; lista fechada, sem texto livre."""

    PRESENCIAL = "presencial"
    TELEFONE = "telefone"
    EMAIL = "email"
    CARTA = "carta"
    OUTRO = "outro"


class FormaEntrega(StrEnum):
    """O registro da entrega da cópia (RF-1009, §4.10); sem nome de quem recebeu."""

    EM_MAOS = "em_maos"  # ao próprio titular, na clínica
    REPRESENTANTE = "representante"  # a representante legal ou procurador
    EMAIL = "email"
    CORREIO = "correio"


# §15: o pedido de eliminação de dado sob guarda obrigatória é negado com este fundamento.
FUNDAMENTO_GUARDA = (
    "Os dados estão sob guarda obrigatória: a eliminação não se aplica aos dados necessários ao cumprimento de "
    "obrigação legal ou regulatória (art. 16, I, da Lei nº 13.709/2018), e o prontuário do paciente deve ser "
    "guardado por no mínimo 20 anos (Lei nº 13.787/2018)."
)


@dataclass(frozen=True, slots=True)
class Requisicao:
    id: int
    paciente_id: int
    nome: str
    prontuario: str
    tipo: TipoRequisicao
    canal: Canal
    recebida_em: date
    situacao: SituacaoRequisicao
    desfecho: str | None
    atendida_em: datetime | None
    atendente_id: int | None
    prazo: date  # derivado (DD-18): recebida_em + parâmetro titular_prazo
    dias_restantes: int  # negativo: prazo vencido


@dataclass(frozen=True, slots=True)
class PacoteTitular:
    """Um PDF só: a declaração (DD-105), a ficha (DOC-01) e a cópia dos documentos (MOD-04). Em memória."""

    pdf: bytes
    nome_arquivo: str
    paginas_documentos: int


class TitularService(Protocol):
    def registrar(
        self, contexto: Contexto, paciente_id: int, tipo: TipoRequisicao, canal: Canal, recebida_em: date
    ) -> int:
        """Recepção ou administração. RegraViolada("titular.recebida_no_futuro"); NaoEncontrado (paciente)."""
        ...

    def consultar(
        self, contexto: Contexto, situacao: SituacaoRequisicao | None = SituacaoRequisicao.ABERTA
    ) -> list[Requisicao]:
        """Recepção, administração e visualizador, com o prazo derivado (DD-18), da mais antiga para a mais nova.
        Auditada só a quantidade."""
        ...

    def ver(self, contexto: Contexto, requisicao_id: int) -> Requisicao:
        """titular.requisicao.consultar. NaoEncontrado."""
        ...

    def atender_acesso(self, contexto: Contexto, requisicao_id: int, entrega: FormaEntrega) -> PacoteTitular:
        """Administração (RF-1009). Só pedido aberto de confirmação e acesso: RegraViolada("titular.nao_e_acesso") ou
        ("titular.encerrada"). Auditada com a forma de entrega e o número de páginas; não encerra o pedido."""
        ...

    def concluir(self, contexto: Contexto, requisicao_id: int, desfecho: str) -> None:
        """Administração. RegraViolada("titular.desfecho") se vazio ou longo; ("titular.encerrada")."""
        ...

    def negar(self, contexto: Contexto, requisicao_id: int, fundamento: str) -> None:
        """Administração. RegraViolada("titular.negativa_sem_fundamento") sem o fundamento; ("titular.encerrada")."""
        ...
