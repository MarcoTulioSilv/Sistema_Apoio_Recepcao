"""Carga inicial do MOD-10 (DDS §14.4): lotes, linhas cifradas da área de trabalho e conferência amostral."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DadosLote:
    id: int
    modo: str  # simulacao, efetivacao
    situacao: str  # em_andamento, concluida, falhou, aceita
    contagens: dict[str, Any] | None
    iniciado_em: datetime
    concluido_em: datetime | None
    aceito_em: datetime | None
    aceito_por: int | None
    ativos_confirmados: int | None


@dataclass(frozen=True, slots=True)
class DadosLinha:
    id: int
    lote_id: int
    planilha: str
    numero_linha: int
    conteudo_cifrado: bytes
    nonce: bytes
    paciente_id: int | None
    excecao_codigo: str | None
    excecao_tratada: str | None  # importada_manual, descartada
    excecao_motivo: str | None
    avisos: tuple[str, ...]
    amostra_rodada: int | None


@dataclass(frozen=True, slots=True)
class DadosConferencia:
    paciente_id: int
    campo: str
    resultado: str  # conferido, divergente
    conferido_por: int
    conferido_em: datetime


class RepositorioCarga(Protocol):
    def efetivacao(self, travar: bool = False) -> DadosLote | None:
        """O lote da efetivação (no máximo um, DD-72), aceito ou não."""
        ...

    def ultimo_lote(self) -> DadosLote | None:
        """A efetivação, se houver; senão, a simulação mais recente."""
        ...

    def criar_lote(self, modo: str, iniciado_em: datetime) -> int: ...

    def concluir_lote(self, lote_id: int, situacao: str, contagens: dict[str, Any], em: datetime) -> None: ...

    def apagar_linhas_de_simulacao(self) -> int:
        """O relatório de uma simulação vale até a próxima execução: a anterior sai (minimização, DD-69)."""
        ...

    def criar_linha(
        self,
        lote_id: int,
        planilha: str,
        numero_linha: int,
        cifrado: bytes,
        nonce: bytes,
        paciente_id: int | None,
        excecao_codigo: str | None,
        avisos: Sequence[str],
    ) -> int: ...

    def linhas(self, lote_id: int) -> list[DadosLinha]:
        """Em ordem de planilha e de linha."""
        ...

    def linha(self, linha_id: int, travar: bool = False) -> DadosLinha | None: ...

    def ligada_a(self, paciente_id: int) -> DadosLinha | None:
        """A linha da carga que já aponta para o paciente, importada pela carga ou à mão."""
        ...

    def tratar(self, linha_id: int, tratamento: str, motivo: str, paciente_id: int | None) -> None: ...

    def marcar_amostra(self, linha_ids: Sequence[int], rodada: int) -> None: ...

    def conferencias(self) -> list[DadosConferencia]: ...

    def registrar_conferencia(self, paciente_id: int, campo: str, resultado: str, por: int, em: datetime) -> bool:
        """Cria ou substitui o resultado do campo; False se já era o mesmo."""
        ...

    def aceitar(self, lote_id: int, em: datetime, por: int, ativos_confirmados: int) -> None: ...

    def apagar_area_de_trabalho(self) -> tuple[int, int]:
        """Linhas e conferências apagadas no aceite (DD-69)."""
        ...
