"""Dados do MOD-04 Documentos (DDS §8.7): tipos, ingestões e documentos. Instantes em UTC, com fuso."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

EstadoIngestao = Literal[
    "aberta", "recebida", "em_processamento", "aguardando_conferencia", "incorporada", "rejeitada", "expirada",
    "cancelada",
]  # fmt: skip
Origem = Literal["scanner", "webcam"]


@dataclass(frozen=True, slots=True)
class TipoGravado:
    codigo: str
    nome: str
    familia: str
    anos_retencao: int
    origem: Origem
    campos_extracao: tuple[str, ...]
    checklist: str = "nao"  # "nao", "sempre" ou "se_convenio" (RF-706)


@dataclass(frozen=True, slots=True)
class IngestaoGravada:
    id: bytes
    paciente_id: int
    tipo: str
    origem: Origem
    vinculo: str | None
    substitui_id: bytes | None
    estado: EstadoIngestao
    motivo_rejeicao: str | None
    token_hash: str | None
    hash_entrada: str | None
    hash_reconstruido: str | None
    paginas: int | None
    campos_candidatos_cifrados: bytes | None
    documento_id: bytes | None
    criada_em: datetime
    criada_por: int
    atualizada_em: datetime


@dataclass(frozen=True, slots=True)
class DocumentoGravado:
    id: bytes
    paciente_id: int
    tipo: str
    versao: int
    substitui_id: bytes | None
    arquivo: str
    chave_cifrada: bytes | None
    nonce: bytes
    hash_sha256: str
    paginas: int
    origem: Origem
    capturado_em: datetime
    capturado_por: int
    local_digitalizacao: str
    descartado_em: datetime | None
    bloqueado_em: datetime | None
    bloqueio_motivo: str | None


class RepositorioDocumentos(Protocol):
    # ---------------------------------------------------------------- tipos e pacientes
    def tipo(self, codigo: str) -> TipoGravado | None: ...

    def tipos(self) -> list[TipoGravado]: ...

    def paciente_ativo(self, paciente_id: int) -> bool:
        """Existe e não está anulado (o MOD-04 lê só o identificador do paciente, SEG-14)."""
        ...

    # ---------------------------------------------------------------- ingestões
    def criar_ingestao(self, ingestao: IngestaoGravada) -> None: ...

    def ingestao(self, ingestao_id: bytes, travar: bool = False) -> IngestaoGravada | None: ...

    def salvar_ingestao(self, ingestao: IngestaoGravada) -> None:
        """Grava as colunas que mudam: estado, motivo, token, hashes, páginas, candidatos, documento e atualizada_em."""
        ...

    def tomar_da_fila(self) -> IngestaoGravada | None:
        """A recebida mais antiga, travada com SKIP LOCKED (DD-33): outro worker passa à seguinte."""
        ...

    def em_estado(self, estados: Sequence[EstadoIngestao]) -> list[IngestaoGravada]: ...

    def criadas_antes(self, estados: Sequence[EstadoIngestao], limite: datetime) -> list[IngestaoGravada]: ...

    def ingestoes_do_paciente(self, paciente_id: int, estados: Sequence[EstadoIngestao]) -> list[IngestaoGravada]: ...

    def ids_de_ingestoes(self, ids: Sequence[bytes]) -> dict[bytes, EstadoIngestao]:
        """O estado de cada id existente, para a limpeza da quarentena."""
        ...

    # ---------------------------------------------------------------- documentos
    def criar_documento(self, documento: DocumentoGravado) -> None: ...

    def documento(self, documento_id: bytes) -> DocumentoGravado | None: ...

    def documento_com_hash(self, hash_sha256: str) -> bytes | None:
        """O documento com este conteúdo, se já existe (o hash é único, §8.7)."""
        ...

    def sucessor(self, documento_id: bytes) -> bytes | None:
        """A versão que substitui esta, se houver (a vigente é a que não tem sucessor, DD-36)."""
        ...

    def do_paciente(self, paciente_id: int) -> list[DocumentoGravado]:
        """Todas as versões, descartadas inclusive, por tipo e versão."""
        ...

    def nao_descartados(self) -> list[DocumentoGravado]:
        """O acervo vivo, para a retenção (DD-01) e as conferências periódicas (DD-41)."""
        ...

    def ultimo_documento_em(self, paciente_ids: Sequence[int]) -> dict[int, datetime]:
        """A captura mais recente de cada paciente, descartados inclusive: é o último registro (DD-01)."""
        ...

    def revincular(self, documento_ids: Sequence[bytes], paciente_id: int) -> None: ...

    def descartar(self, documento_id: bytes, instante: datetime) -> None:
        """Apaga a chave e marca o descarte (DD-04); a linha fica como registro."""
        ...

    def bloquear(self, documento_id: bytes, instante: datetime, motivo: str) -> None:
        """Só se ainda não estiver bloqueado: o primeiro motivo prevalece (P-19)."""
        ...

    def desbloquear(self, documento_id: bytes) -> None: ...

    def tipos_presentes(self, paciente_ids: Sequence[int] | None) -> dict[int, set[str]]:
        """Os tipos com algum documento não descartado, por paciente (RF-706)."""
        ...

    def bloqueados(self) -> list[DocumentoGravado]: ...

    def arquivos(self) -> set[str]:
        """Os nomes de arquivo de todas as linhas, descartadas inclusive, para a varredura de órfãos (DD-37)."""
        ...

    def acervo_depois_de(self, documento_id: bytes | None, limite: int) -> list[DocumentoGravado]:
        """Os não descartados em ordem de id, a partir do cursor: as rotinas longas param e retomam (DD-64)."""
        ...
