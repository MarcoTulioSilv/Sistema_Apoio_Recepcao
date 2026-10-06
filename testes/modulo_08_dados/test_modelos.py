from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base


class Dono(Base):
    __tablename__ = "teste_dono"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Item(Base):
    __tablename__ = "teste_item"
    __table_args__ = (
        UniqueConstraint("dono_id", "codigo"),
        Index(None, "codigo"),
        CheckConstraint("codigo <> ''", name="codigo"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dono_id: Mapped[int] = mapped_column(ForeignKey("teste_dono.id"))
    codigo: Mapped[str] = mapped_column(String(10))


@pytest.mark.requisito("DDS-12.2")
def test_nomes_de_restricao_seguem_a_convencao_das_migracoes() -> None:
    tabela = Item.__table__
    nomes = {str(r.name) for r in tabela.constraints} | {str(i.name) for i in tabela.indexes}
    assert nomes == {
        "pk_teste_item",
        "fk_teste_item__dono_id",
        "uq_teste_item__dono_id_codigo",
        "ix_teste_item__codigo",
        "ck_teste_item__codigo",
    }
