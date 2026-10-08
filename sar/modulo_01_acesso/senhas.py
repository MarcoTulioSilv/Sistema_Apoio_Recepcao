"""Hash de senha com bcrypt (AD-19, DD-83). O custo é 12 em produção; os testes podem usar um custo menor."""

from __future__ import annotations

import secrets

import bcrypt

CUSTO = 12  # DD-83
_MAXIMO_BYTES = 72  # o bcrypt 5 recusa com erro, em vez de truncar


class Hasher:
    def __init__(self, custo: int = CUSTO) -> None:
        self._custo = custo
        # Login inexistente confere contra este hash, para gastar o mesmo tempo de um login real (§5.2).
        self._ficticio = self.gerar(secrets.token_urlsafe(24))

    def gerar(self, senha: str) -> str:
        return bcrypt.hashpw(senha.encode(), bcrypt.gensalt(self._custo)).decode("ascii")

    def conferir(self, senha: str, senha_hash: str | None) -> bool:
        """Sempre faz uma verificação, mesmo sem hash ou com entrada acima de 72 bytes: o tempo de resposta
        não pode revelar se o login existe nem o que foi digitado."""
        dados = senha.encode()
        confere = bcrypt.checkpw(dados[:_MAXIMO_BYTES], (senha_hash or self._ficticio).encode("ascii"))
        return confere and senha_hash is not None and len(dados) <= _MAXIMO_BYTES
