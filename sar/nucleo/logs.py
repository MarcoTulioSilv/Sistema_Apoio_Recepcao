"""Log técnico estruturado e minimizado (DD-81, RNF-624).

Uma linha JSON por evento, só com os campos de CAMPOS. A mensagem, os argumentos e o traceback nunca são
escritos: a mensagem do log tem de ser um código de evento (`modulo.acao`), e os dados vão em `extra`, só
nos campos permitidos. Mensagem de biblioteca de terceiros vira um código fixo, sem o texto. Exceção vira
o nome da classe (`erro`) e, em erro de banco, o nome da restrição (`restricao`), que o MOD-08 anexa à
exceção.

Uso nos módulos:  log.warning("uow.impasse.repetido", extra={"resultado": "tentativa_2_de_3"})
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

CAMPOS = (
    "instante",
    "nivel",
    "processo",
    "modulo",
    "evento",
    "requisicao_id",
    "usuario_id",
    "perfil",
    "duracao_ms",
    "resultado",
    "erro",
    "restricao",
)

ATRIBUTO_RESTRICAO = "sar_restricao"  # anexado à exceção de banco pelo MOD-08
EVENTO_DESCARTADO = "externo.mensagem_descartada"
VALOR_DESCARTADO = "valor_descartado"
RUIDOSOS = ("alembic", "sqlalchemy", "werkzeug")  # mensagens livres que só gerariam linhas descartadas

_EVENTO = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
_CODIGO = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")  # resultado, erro, restrição e perfil: só códigos
_REQUISICAO = re.compile(r"^[0-9a-f]{32}$")

_requisicao_id: ContextVar[str | None] = ContextVar("requisicao_id", default=None)
_usuario_id: ContextVar[int | None] = ContextVar("usuario_id", default=None)
_perfil: ContextVar[str | None] = ContextVar("perfil", default=None)


def novo_requisicao_id() -> str:
    return secrets.token_hex(16)


def iniciar_requisicao(requisicao_id: str | None = None) -> str:
    """Marca o início de uma requisição ou execução: toda linha de log seguinte leva este id."""
    ident = requisicao_id if requisicao_id and _REQUISICAO.match(requisicao_id) else novo_requisicao_id()
    _requisicao_id.set(ident)
    _usuario_id.set(None)
    _perfil.set(None)
    return ident


def identificar_usuario(usuario_id: int | None, perfil: str | None) -> None:
    """Chamado depois da autenticação (MOD-01): só o id interno e o perfil, nunca o nome."""
    _usuario_id.set(usuario_id)
    _perfil.set(perfil)


def encerrar_requisicao() -> None:
    _requisicao_id.set(None)
    _usuario_id.set(None)
    _perfil.set(None)


def requisicao_atual() -> str | None:
    return _requisicao_id.get()


def campos_do_erro(erro: BaseException) -> dict[str, str]:
    """Tipo e, se houver, restrição violada; nunca a mensagem nem os argumentos."""
    campos = {"erro": type(erro).__name__}
    restricao = getattr(erro, ATRIBUTO_RESTRICAO, None)
    if isinstance(restricao, str):
        campos["restricao"] = restricao
    return campos


def _codigo(valor: object) -> str:
    return valor if isinstance(valor, str) and _CODIGO.match(valor) else VALOR_DESCARTADO


class FormatadorJson(logging.Formatter):
    def __init__(self, processo: str) -> None:
        super().__init__()
        self._processo = processo

    def format(self, record: logging.LogRecord) -> str:
        mensagem = record.msg
        evento = mensagem if isinstance(mensagem, str) and not record.args and _EVENTO.match(mensagem) else None
        dados: dict[str, Any] = {
            "instante": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "nivel": record.levelname.lower(),
            "processo": self._processo,
            "modulo": record.name,
            "evento": evento or EVENTO_DESCARTADO,
        }
        requisicao = getattr(record, "requisicao_id", None) or _requisicao_id.get()
        if isinstance(requisicao, str) and _REQUISICAO.match(requisicao):
            dados["requisicao_id"] = requisicao
        usuario = getattr(record, "usuario_id", None) or _usuario_id.get()
        if isinstance(usuario, int) and not isinstance(usuario, bool):
            dados["usuario_id"] = usuario
        perfil = getattr(record, "perfil", None) or _perfil.get()
        if perfil is not None:
            dados["perfil"] = _codigo(perfil)
        duracao = getattr(record, "duracao_ms", None)
        if isinstance(duracao, int | float) and not isinstance(duracao, bool):
            dados["duracao_ms"] = round(duracao, 1)
        for campo in ("resultado", "erro", "restricao"):
            if hasattr(record, campo):
                dados[campo] = _codigo(getattr(record, campo))
        if record.exc_info and record.exc_info[1] is not None:
            for campo, valor in campos_do_erro(record.exc_info[1]).items():
                dados.setdefault(campo, _codigo(valor))
        return json.dumps(dados, ensure_ascii=False, separators=(",", ":"))


_fabrica_original = logging.getLogRecordFactory()


def _registro_com_contexto(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Carimba requisição, usuário e perfil na criação do registro, e não na formatação: um handler que
    formate depois (em fila, por exemplo) ainda leva o contexto certo."""
    registro = _fabrica_original(*args, **kwargs)
    registro.requisicao_id = _requisicao_id.get()
    registro.usuario_id = _usuario_id.get()
    registro.perfil = _perfil.get()
    return registro


def configurar(processo: str, nivel: int = logging.INFO) -> None:
    """Liga o formato da DD-81 na raiz do logging, para o processo inteiro (web, worker ou linha de comando)."""
    raiz = logging.getLogger()
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)
    saida = logging.StreamHandler(sys.stderr)
    saida.setFormatter(FormatadorJson(processo))
    raiz.addHandler(saida)
    raiz.setLevel(nivel)
    logging.setLogRecordFactory(_registro_com_contexto)
    logging.captureWarnings(True)
    for ruidoso in RUIDOSOS:
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
