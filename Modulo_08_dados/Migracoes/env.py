"""Ambiente do Alembic do SAR. A URL vem do alembic.ini ou da variável SAR_URL_MIGRACAO (usuário sar_migracao)."""
import os
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
url = os.environ.get("SAR_URL_MIGRACAO")
if url:
    config.set_main_option("sqlalchemy.url", url)


def run_migrations_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.",
                                poolclass=pool.NullPool)
    with engine.connect() as conn:
        conn.exec_driver_sql("SET time_zone = '+00:00'")
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


run_migrations_online()
