"""Contrato público do MOD-04 Documentos (DDS §8.8). Fora do módulo, importe só daqui."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import BinaryIO, Protocol

from sar.nucleo.contexto import Contexto


class EstadoIngestao(str, Enum):  # §8.4
    ABERTA = "aberta"
    RECEBIDA = "recebida"
    EM_PROCESSAMENTO = "em_processamento"
    AGUARDANDO_CONFERENCIA = "aguardando_conferencia"
    INCORPORADA = "incorporada"
    REJEITADA = "rejeitada"
    EXPIRADA = "expirada"
    CANCELADA = "cancelada"


FINAIS = frozenset({EstadoIngestao.INCORPORADA, EstadoIngestao.REJEITADA, EstadoIngestao.EXPIRADA,
                    EstadoIngestao.CANCELADA})  # fmt: skip

# Motivos da recepcionista na conferência (§8.3, etapa 7).
MOTIVOS_REJEICAO = ("ilegivel", "paciente_errado", "tipo_errado")


@dataclass(frozen=True, slots=True)
class IngestaoAberta:
    id: str  # 32 hexadecimais
    token: str  # de uso único (DD-05); só existe nesta resposta, o banco guarda o hash


@dataclass(frozen=True, slots=True)
class CampoCandidato:
    nome: str  # campo do cadastro: cep, cns, cpf, carteirinha, data_nascimento
    valor: str
    confianca: str  # "alta" ou "baixa": a tela destaca a baixa (RF-704)


@dataclass(frozen=True, slots=True)
class SituacaoIngestao:
    id: str
    paciente_id: int
    tipo: str
    origem: str
    estado: EstadoIngestao
    motivo: str | None  # código da rejeição (SEG-12)
    paginas: int | None


@dataclass(frozen=True, slots=True)
class Conferencia:
    """O que a tela de conferência mostra além da imagem: os candidatos, só enquanto a ingestão espera (P-18)."""

    situacao: SituacaoIngestao
    campos: tuple[CampoCandidato, ...]
    vinculo: str | None


class IngestaoService(Protocol):
    def abrir(
        self,
        contexto: Contexto,
        paciente_id: int,
        tipo: str,
        origem: str,
        vinculo: str | None = None,
        substitui_id: str | None = None,
        motivo: str | None = None,
    ) -> IngestaoAberta:
        """Etapa 1 (§8.3). `AcessoNegado`; `RegraViolada` com tipo inexistente, origem incompatível, paciente anulado
        ou versão substituída que não é a vigente do mesmo paciente e tipo. Nova versão exige motivo (RF-708)."""
        ...

    def receber_pagina(self, ingestao_id: str, token: str, numero: int, fluxo: BinaryIO) -> None:
        """Etapa 2, uma página por chamada (§8.5). `AcessoNegado` com token inválido, vencido ou já usado;
        `RegraViolada("arquivo.tamanho")` ou `RegraViolada("pagina.numero")`."""
        ...

    def concluir(self, ingestao_id: str, token: str, paginas: int) -> None:
        """Fim do envio: a ingestão vai à fila e o token deixa de valer. `RegraViolada("paginas.faltando")`."""
        ...

    def cancelar(self, contexto: Contexto, ingestao_id: str) -> None:
        """Só a aberta; o que chegou à quarentena é apagado."""
        ...

    def situacao(self, contexto: Contexto, ingestao_id: str) -> SituacaoIngestao:
        """Para a tela acompanhar a ingestão (sem os candidatos). `NaoEncontrado`."""
        ...

    def conferir(self, contexto: Contexto, ingestao_id: str) -> Conferencia:
        """Abre a conferência (auditada). `RegraViolada("ingestao.estado")` fora de "aguardando conferência"."""
        ...

    def pagina_em_conferencia(self, contexto: Contexto, ingestao_id: str) -> tuple[bytes, str]:
        """O documento reconstruído, da quarentena, com o formato ("pdf" ou "jpeg"). `IntegridadeViolada`."""
        ...

    def incorporar(self, contexto: Contexto, ingestao_id: str) -> str:
        """Etapa 8: guarda no cofre e devolve o id do documento. Os campos confirmados vão ao MOD-02 pela tela, pelo
        contrato de atualização do cadastro (DD-40). `RegraViolada("ingestao.estado")`;
        `RegraViolada("documento.repetido")` se o mesmo conteúdo já foi incorporado."""
        ...

    def rejeitar(self, contexto: Contexto, ingestao_id: str, motivo: str) -> None:
        """`RegraViolada("ingestao.motivo")` fora de MOTIVOS_REJEICAO; `RegraViolada("ingestao.estado")`."""
        ...


# ------------------------------------------------------------------ documentos (§8.6)
DESCARTAR = "documento.descartar_fim_retencao"  # operação autorizada (DEC-42, DD-04)
DESBLOQUEAR = "documento.desbloquear"  # operação autorizada, só do bloqueio por rescan (P-19)


@dataclass(frozen=True, slots=True)
class VersaoDocumento:
    id: str
    tipo: str
    nome_tipo: str
    versao: int
    paginas: int
    origem: str
    capturado_em: datetime
    capturado_por: int
    descartado_em: datetime | None
    bloqueio: str | None  # "rescan" ou "hash_divergente" (P-19)


@dataclass(frozen=True, slots=True)
class DocumentoDoTipo:
    """A versão vigente e as anteriores, da mais nova para a mais antiga (DD-36)."""

    tipo: str
    nome_tipo: str
    vigente: VersaoDocumento
    anteriores: tuple[VersaoDocumento, ...]


@dataclass(frozen=True, slots=True)
class PaginaDocumento:
    conteudo: bytes
    tipo_midia: str  # "image/jpeg"


class DocumentoService(Protocol):
    def listar(self, contexto: Contexto, paciente_id: int) -> list[DocumentoDoTipo]:
        """Metadados (RNF-626), auditado com a quantidade. `AcessoNegado`."""
        ...

    def pagina(self, contexto: Contexto, documento_id: str, numero: int) -> PaginaDocumento:
        """Auditada antes da entrega (RF-710); decifra em memória e confere o hash (DD-38). `IntegridadeViolada` também
        bloqueia o documento; `RegraViolada("documento.bloqueado")`, `RegraViolada("documento.descartado")`."""
        ...

    def baixar(self, contexto: Contexto, documento_id: str) -> tuple[bytes, str]:
        """Só a administração (P-17): o arquivo inteiro e o tipo de mídia. Mesmos erros de `pagina`."""
        ...

    def revincular(self, contexto: Contexto, documento_id: str, paciente_id: int, motivo: str) -> None:
        """Leva todas as versões do documento ao paciente certo (RF-713) e publica `DocumentoRevinculado`.
        `RegraViolada` com motivo vazio, paciente anulado ou o mesmo paciente."""
        ...
