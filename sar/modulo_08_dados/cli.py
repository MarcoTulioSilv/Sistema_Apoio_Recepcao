"""Linha de comando `sar` (DDS §12.1): migrar o banco e criar os usuários por processo.

  sar migrar [alvo]          aplica as migrações até o alvo (padrão: head), como sar_migracao
  sar reverter alvo          desfaz até o alvo; só antes do go-live (DD-60)
  sar criar-usuarios-banco   cria sar_web, sar_worker e sar_expurgo com as senhas dos segredos (DD-58)

Conexão pelas variáveis SAR_BANCO_HOST, SAR_BANCO_PORTA e SAR_BANCO_NOME; senhas pelos segredos
(SAR_SEGREDOS).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError

from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.modulo_08_dados.erros_banco import anotar_restricao
from sar.modulo_08_dados.segredos import ler_segredo
from sar.nucleo.logs import campos_do_erro, configurar

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sar", description="Linha de comando do SAR")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("migrar", help="aplica as migrações")
    p.add_argument("alvo", nargs="?", default="head")
    p = sub.add_parser("reverter", help="desfaz migrações (só antes do go-live)")
    p.add_argument("alvo")
    p = sub.add_parser("criar-usuarios-banco", help="cria os usuários por processo")
    p.add_argument("--admin", default="root", help="usuário com privilégio de criar usuários")
    p.add_argument("--segredo-admin", default="mysql_root", help="segredo com a senha do administrador")
    args = parser.parse_args(argv)
    configurar("cli")

    try:
        if args.comando == "migrar":
            migrar(args.alvo)
        elif args.comando == "reverter":
            reverter(args.alvo)
        else:
            criar_usuarios_banco(args.admin, args.segredo_admin)
    except Exception as erro:
        if isinstance(erro, DBAPIError):
            anotar_restricao(erro)
        # Sem traceback: o texto de um erro de banco traz o SQL, que aqui pode conter senha (DD-81).
        detalhe = " ".join(f"{campo}={valor}" for campo, valor in campos_do_erro(erro).items())
        print(f"Falhou: {detalhe}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
