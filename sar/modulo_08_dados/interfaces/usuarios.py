"""Usuários do sistema (DDS §5.1). Nunca excluídos (RF-1005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DadosUsuario:
    id: int
    nome: str
    login: str
    senha_hash: str
    perfil: str
    ativo: bool
    deve_trocar_senha: bool
    termo_ciencia_em: datetime | None
    tentativas_falhas: int
    bloqueado_ate: datetime | None
    versao: int


class RepositorioUsuario(Protocol):
    def por_login(self, login: str) -> DadosUsuario | None: ...

    def por_id(self, id: int) -> DadosUsuario | None: ...

    def travar(self, id: int) -> None:
        """Trava a linha até o commit: duas entradas do mesmo usuário ao mesmo tempo se serializam (P-02)."""
        ...

    def incrementar_falhas(self, id: int) -> int:
        """Soma uma falha no próprio banco e devolve o total: tentativas em paralelo não se perdem, porque a
        linha fica travada até o commit. Os contadores do bloqueio não mudam a versão (DD-17), para uma
        tentativa de login não conflitar com a tela do TI."""
        ...

    def definir_bloqueio(self, id: int, ate: datetime | None) -> None: ...

    def zerar_falhas(self, id: int) -> None: ...

    def trocar_senha(self, id: int, senha_hash: str, deve_trocar: bool) -> None:
        """Muda a versão (DD-17)."""
        ...
