"""Comandos de banco da linha de comando `sar` (DDS §12.1): migrar e criar os usuários por processo.
O ponto de entrada fica em sar/cli.py.

Conexão pelas variáveis SAR_BANCO_HOST, SAR_BANCO_PORTA e SAR_BANCO_NOME; senhas pelos segredos
(SAR_SEGREDOS).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from alembic import command
from alembic.config import Config

from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.modulo_08_dados.segredos import ler_segredo

PASTA = Path(__file__).resolve().parent
SENHAS = {"{{SENHA_WEB}}": "sar_web", "{{SENHA_WORKER}}": "sar_worker", "{{SENHA_EXPURGO}}": "sar_expurgo"}


def _config_alembic() -> Config:
    url = ConfigBanco.do_ambiente("sar_migracao").url().render_as_string(hide_password=False)
    os.environ["SAR_URL_MIGRACAO"] = url  # lida pelo env.py das migrações
    config = Config()
    config.set_main_option("script_location", str(PASTA / "migracoes"))
    return config


def migrar(alvo: str) -> None:
    command.upgrade(_config_alembic(), alvo)
    print(f"Banco migrado até {alvo}.")


def reverter(alvo: str) -> None:
    command.downgrade(_config_alembic(), alvo)
    print(f"Banco revertido até {alvo}.")


def comandos_usuarios(sql: str, senhas: dict[str, str]) -> list[str]:
    """Substitui as senhas no usuarios_banco.sql e devolve os comandos, sem comentários."""
    for marcador, senha in senhas.items():
        if not re.fullmatch(r"[A-Za-z0-9_\-.~]{16,}", senha):
            raise ValueError(f"senha de {SENHAS.get(marcador, marcador)} fora do formato aceito")
        sql = sql.replace(marcador, senha)
    if "{{" in sql:
        raise ValueError("marcador de senha sem valor no usuarios_banco.sql")
    sem_comentarios = re.sub(r"--[^\n]*", "", sql)
    return [c.strip() for c in sem_comentarios.split(";") if c.strip()]


def criar_usuarios_banco(admin: str, segredo_admin: str) -> None:
    sql = (PASTA / "usuarios_banco.sql").read_text(encoding="utf-8")
    senhas = {marcador: ler_segredo(usuario) for marcador, usuario in SENHAS.items()}
    base = ConfigBanco.do_ambiente("sar_migracao")
    config = ConfigBanco(admin, ler_segredo(segredo_admin), base.host, base.porta, base.nome)
    engine = criar_engine(config)
    try:
        with engine.begin() as conexao:
            # Pelo cursor do driver e sem parâmetros: o '%' de 'usuario'@'%' não é marcador de parâmetro.
            cursor = conexao.connection.cursor()
            try:
                for comando in comandos_usuarios(sql, senhas):
                    cursor.execute(comando)
            finally:
                cursor.close()
    finally:
        engine.dispose()
    print("Usuários do banco criados.")
