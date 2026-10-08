"""Trilha de auditoria: o que a verificação, o aviso de integridade, a âncora e o expurgo leem e gravam."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Elo:
    """Um registro da trilha, com os campos que entram no hash (DDS §3.10). Instantes em UTC, com fuso."""

    id: int
    instante: datetime
    usuario_id: int | None
    autorizador_id: int | None
    operacao: str
    entidade: str
    entidade_id: str | None
    alteracoes: str | None
    motivo: str | None
    origem: str | None
    sessao_id: int | None
    requisicao_id: str | None
    versao_formato: int
    hash_anterior: str
    hash_registro: str


@dataclass(frozen=True, slots=True)
class Cabeca:
    ultimo_id: int
    ultimo_hash: str


@dataclass(frozen=True, slots=True)
class Corte:
    primeiro_id_remanescente: int
    hash_anterior: str
    executado_em: datetime
    registros_expurgados: int


@dataclass(frozen=True, slots=True)
class Ancora:
    id: int
    ate_registro_id: int
    hash: str
    registrada_em: datetime


@dataclass(frozen=True, slots=True)
class Aviso:
    id: int
    detectado_em: datetime
    registro_divergente_id: int
    encerrado_em: datetime | None
    encerrado_por: int | None
    explicacao: str | None


class RepositorioTrilha(Protocol):
    def cabeca(self) -> Cabeca: ...

    def ultimo_corte(self) -> Corte | None: ...

    def elos(self, de_id: int, ate_id: int) -> Iterator[Elo]:
        """Em ordem de id, lidos em lotes: a trilha de cinco anos não cabe na memória."""
        ...

    def elo(self, id: int) -> Elo | None: ...

    def ancoras(self, a_partir_de_id: int) -> list[Ancora]: ...

    def ancora_mais_recente(self) -> Ancora | None: ...

    def ancora_do_registro(self, registro_id: int) -> Ancora | None: ...

    def registrar_ancora(self, ate_registro_id: int, hash: str, em: datetime) -> int: ...

    def avisos_abertos(self) -> list[Aviso]: ...

    def aviso(self, id: int) -> Aviso | None: ...

    def abrir_aviso(self, registro_divergente_id: int, em: datetime) -> int: ...

    def encerrar_aviso(self, id: int, usuario_id: int, em: datetime, explicacao: str) -> None: ...


class RepositorioExpurgo(Protocol):
    """Só para o processo de expurgo (usuário sar_expurgo, DD-58)."""

    def ultimo_elo_antes_de(self, limite: datetime) -> tuple[int, str] | None:
        """Id e hash do registro mais novo com instante anterior ao limite."""
        ...

    def contar_ate(self, id: int) -> int: ...

    def apagar_ate(self, id: int) -> None: ...

    def registrar_corte(
        self, primeiro_id_remanescente: int, hash_anterior: str, em: datetime, quantidade: int
    ) -> None: ...
