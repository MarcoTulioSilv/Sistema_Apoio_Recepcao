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
from sqlalchemy import text

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


class BancoComDados(RuntimeError):
    """A reversão apagaria colunas com dados e pararia no meio (o MySQL não desfaz estrutura): recusada antes."""


# Ficam no zerar-desenvolvimento: a estrutura (versão), os dados fixos das migrações, a cabeça da cadeia (zerada) e, se
# pedido, os usuários. Todo o resto é dado de uso.
FICAM_AO_ZERAR = frozenset(
    {"alembic_version", "auditoria_cabeca", "municipio", "escala", "faixa_etaria", "tipo_documento"}
)


def _contagem(tabela: str) -> int:
    engine = criar_engine(ConfigBanco.do_ambiente("sar_migracao"))
    try:
        with engine.connect() as conexao:
            existe = conexao.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :t"
                ),
                {"t": tabela},
            ).scalar_one()
            if not existe:
                return 0
            # O nome só chega aqui depois de o banco confirmar que a tabela existe; quem chama passa nomes fixos.
            return int(conexao.execute(text(f"SELECT COUNT(*) FROM `{tabela}`")).scalar_one())  # noqa: S608 # nosec B608
    finally:
        engine.dispose()


def reverter(alvo: str) -> None:
    """Visto no uso (17 e 18/11/2026): com pacientes, a volta da 0002 para no meio, mas as voltas anteriores já tinham
    apagado colunas (a 0003 leva a sessão e a requisição de cada registro da trilha), e o migrar seguinte não as
    recria. Com dados, recusa antes de começar (DD-60)."""
    if _contagem("auditoria") or _contagem("paciente"):
        raise BancoComDados()
    command.downgrade(_config_alembic(), alvo)
    print(f"Banco revertido até {alvo}.")


def zerar_desenvolvimento(manter_usuarios: bool) -> dict[str, int]:
    """Apaga todo dado de uso e mantém a estrutura, os dados fixos e, se pedido, os usuários: o jeito prático de repetir
    um ensaio (a carga, por exemplo) no banco de desenvolvimento. A cadeia de auditoria recomeça vazia. Quem chama
    garante que é desenvolvimento."""
    ficam = FICAM_AO_ZERAR | ({"usuario"} if manter_usuarios else set())
    engine = criar_engine(ConfigBanco.do_ambiente("sar_migracao"))
    apagadas: dict[str, int] = {}
    try:
        with engine.begin() as conexao:
            tabelas = [
                nome
                for (nome,) in conexao.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
                )
                if nome not in ficam
            ]
            conexao.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for tabela in tabelas:
                # O nome vem da lista de tabelas do próprio banco (information_schema), nunca de fora.
                resultado = conexao.execute(text(f"DELETE FROM `{tabela}`"))  # noqa: S608 # nosec B608
                apagadas[tabela] = int(getattr(resultado, "rowcount", 0) or 0)
            conexao.execute(
                text("UPDATE auditoria_cabeca SET ultimo_registro_id = 0, ultimo_hash = REPEAT('0', 64) WHERE id = 1")
            )
            if manter_usuarios:
                conexao.execute(text("UPDATE usuario SET tentativas_falhas = 0, bloqueado_ate = NULL"))
            conexao.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        engine.dispose()
    return apagadas


def comandos_usuarios(sql: str, senhas: dict[str, str], banco: str = "sar") -> list[str]:
    """Substitui as senhas e o nome do banco no usuarios_banco.sql e devolve os comandos, sem comentários."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,63}", banco):
        raise ValueError("nome de banco fora do formato aceito")
    sql = sql.replace("{{BANCO}}", banco)
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
                for comando in comandos_usuarios(sql, senhas, base.nome):
                    cursor.execute(comando)
            finally:
                cursor.close()
    finally:
        engine.dispose()
    print("Usuários do banco criados.")
