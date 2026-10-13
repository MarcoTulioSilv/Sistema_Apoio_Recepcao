from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, MetaData, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import sar.modulo_08_dados.modelos.acesso
import sar.modulo_08_dados.modelos.configuracao  # noqa: F401 — registra os modelos reais
from sar.modulo_08_dados.modelos import CONVENCAO_NOMES, Base


class BaseTeste(DeclarativeBase):
    """Separada da Base real, para as tabelas de teste não entrarem na comparação com o banco."""

    metadata = MetaData(naming_convention=CONVENCAO_NOMES)


class Dono(BaseTeste):
    __tablename__ = "teste_dono"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Item(BaseTeste):
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


@pytest.mark.requisito("DD-12")
def test_todo_relacionamento_dos_modelos_reais_e_lazy_raise() -> None:
    relacionamentos = [r for m in Base.registry.mappers for r in m.relationships]
    assert all(r.lazy == "raise" for r in relacionamentos), [str(r) for r in relacionamentos if r.lazy != "raise"]
