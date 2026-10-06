"""Nome da restrição violada, a partir do erro do MySQL (DD-81). Só o nome sai daqui: a mensagem do
servidor traz o valor que violou a restrição (um CPF repetido, por exemplo) e nunca é registrada."""

from __future__ import annotations

import re

from sqlalchemy.exc import DBAPIError

from sar.nucleo.logs import ATRIBUTO_RESTRICAO

_PADROES = {
    1062: re.compile(r"for key '(?:[^'.]+\.)?([a-z0-9_]+)'\s*$"),  # ER_DUP_ENTRY
    3819: re.compile(r"^Check constraint '([a-z0-9_]+)' is violated"),  # ER_CHECK_CONSTRAINT_VIOLATED
    1451: re.compile(r"CONSTRAINT `([a-z0-9_]+)`"),  # ER_ROW_IS_REFERENCED_2
    1452: re.compile(r"CONSTRAINT `([a-z0-9_]+)`"),  # ER_NO_REFERENCED_ROW_2
}


def restricao_violada(erro: DBAPIError) -> str | None:
    argumentos: tuple[object, ...] = getattr(erro.orig, "args", ())
    if len(argumentos) < 2 or not isinstance(argumentos[0], int) or not isinstance(argumentos[1], str):
        return None
    padrao = _PADROES.get(argumentos[0])
    achado = padrao.search(argumentos[1]) if padrao else None
    return achado.group(1) if achado else None


def anotar_restricao(erro: DBAPIError) -> None:
    """Anexa o nome da restrição à exceção, para o log e para o serviço que a traduz em RegraViolada."""
    restricao = restricao_violada(erro)
    if restricao:
        setattr(erro, ATRIBUTO_RESTRICAO, restricao)
