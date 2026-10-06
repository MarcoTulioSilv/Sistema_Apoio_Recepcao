"""Conexão com o MySQL (DDS §12.2, DD-58, DD-59). Único lugar do sistema que cria engine."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy import URL, Engine, create_engine

from sar.modulo_08_dados.segredos import ler_segredo


@dataclass(frozen=True, slots=True)
class ConfigBanco:
    usuario: str  # um usuário por processo (DD-58): sar_web, sar_worker, sar_expurgo, sar_migracao
    senha: str = field(repr=False)
    host: str = "127.0.0.1"
    porta: int = 3306
    nome: str = "sar"

    @classmethod
    def do_ambiente(cls, usuario: str) -> ConfigBanco:
        """Host, porta e banco de SAR_BANCO_HOST, SAR_BANCO_PORTA e SAR_BANCO_NOME; a senha vem do segredo
        com o nome do usuário."""
        return cls(
            usuario=usuario,
            senha=ler_segredo(usuario),
            host=os.environ.get("SAR_BANCO_HOST", "127.0.0.1"),
            porta=int(os.environ.get("SAR_BANCO_PORTA", "3306")),
            nome=os.environ.get("SAR_BANCO_NOME", "sar"),
        )

    def url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.usuario,
            password=self.senha,
            host=self.host,
            port=self.porta,
            database=self.nome,
        )


def criar_engine(config: ConfigBanco) -> Engine:
    """Conexão em UTC (§12.2) e em READ COMMITTED (DD-59). Os parâmetros nunca entram no texto dos erros
    (DD-81): são os valores gravados, com dado de paciente."""
    return create_engine(
        config.url(),
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"charset": "utf8mb4", "init_command": "SET time_zone = '+00:00'"},
    )
