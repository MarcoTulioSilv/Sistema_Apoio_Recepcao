"""Modelos ORM (DDS §3.1, §12.1): um arquivo por módulo, relacionamentos com lazy="raise" (DD-12).

Cada módulo traz os seus modelos no incremento em que é construído. Os nomes de restrição seguem a
convenção da §12.2, a mesma das migrações: <tipo>_<tabela>__<colunas ou nome>.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

CONVENCAO_NOMES = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s__%(column_0_N_name)s",
    "uq": "uq_%(table_name)s__%(column_0_N_name)s",
    "ix": "ix_%(table_name)s__%(column_0_N_name)s",
    "ck": "ck_%(table_name)s__%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO_NOMES)
