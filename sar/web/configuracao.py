"""O que a web recebe de quem a monta (sar/wsgi.py): os serviços, pelos contratos, e a configuração. A web não
importa a raiz de composição, que traz o banco consigo (contrato "Rotas não acessam o banco")."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sar.modulo_01_acesso.contrato import AuthService, SessionManager


@dataclass(frozen=True, slots=True)
class ConfigWeb:
    origem: str  # esquema://servidor[:porta], exata (DD-80): conferida no Origin de todo POST (DD-84)
    desenvolvimento: bool = False
    superusuarios: frozenset[int] = field(default_factory=frozenset)  # ids; só em desenvolvimento (DD-85)
    proxies_confiaveis: int = 0  # Caddy na frente: 1; o endereço do cliente vem do X-Forwarded-For

    def __post_init__(self) -> None:
        partes = urlsplit(self.origem)
        if partes.scheme not in ("http", "https") or not partes.netloc or partes.path not in ("", "/"):
            raise ValueError("SAR_ORIGEM deve ser esquema://servidor[:porta], sem caminho")
        if partes.scheme != "https" and not self.desenvolvimento:
            raise ValueError("fora do desenvolvimento a origem é HTTPS (DD-80)")
        if self.superusuarios and not self.desenvolvimento:
            raise ValueError("superusuário só existe em desenvolvimento (DD-85)")

    @property
    def origem_normalizada(self) -> str:
        return self.origem.rstrip("/")


@dataclass(frozen=True, slots=True)
class ServicosWeb:
    autenticacao: AuthService
    sessoes: SessionManager
