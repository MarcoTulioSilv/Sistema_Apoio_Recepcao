"""Repositório de parâmetros (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.parametros import ValorGravado
from sar.modulo_08_dados.modelos.configuracao import Parametro


def _valor(linha: Parametro) -> ValorGravado:
    return ValorGravado(linha.nome, linha.valor, linha.alterado_em.replace(tzinfo=UTC), linha.alterado_por)


class RepositorioParametroSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def valor(self, nome: str) -> ValorGravado | None:
        linha = self._s.get(Parametro, nome)
        return _valor(linha) if linha is not None else None

    def todos(self) -> list[ValorGravado]:
        return [_valor(linha) for linha in self._s.scalars(select(Parametro).order_by(Parametro.nome))]

    def gravar(self, nome: str, valor: str, em: datetime, por: int) -> None:
        linha = self._s.get(Parametro, nome)
        instante = em.astimezone(UTC).replace(tzinfo=None)
        if linha is None:
            self._s.add(Parametro(nome=nome, valor=valor, alterado_em=instante, alterado_por=por))
        else:
            linha.valor, linha.alterado_em, linha.alterado_por = valor, instante, por
        self._s.flush()
