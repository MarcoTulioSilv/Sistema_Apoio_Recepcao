"""Forma canônica da trilha de auditoria (DDS §3.10), sem banco: usada pela gravação (cadeia.py, MOD-08) e
pela verificação (MOD-01). Fica separada porque o MOD-01 não pode importar nada que importe o SQLAlchemy,
nem indiretamente (contrato "Só o MOD-08 fala com o banco").

Formato, versão 1:
- JSON com chaves ordenadas, separadores sem espaço, UTF-8 sem escape de caracteres não ASCII;
- instante em ISO 8601 UTC com microssegundos e "Z"; datas AAAA-MM-DD; decimais como texto; nulo como null;
  bytes proibidos; ponto flutuante também (use Decimal), para o hash não depender de arredondamento;
- `alteracoes` é serializado à parte, gravado como texto, e entra no JSON do registro como esse texto: assim o
  hash é recalculado a partir da linha do banco, sem reserializar nada (§3.10, item 6);
- hash_registro = SHA-256(hash_anterior + quebra de linha + json), em hexadecimal; o primeiro elo usa 64 zeros.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

VERSAO_FORMATO = 1
HASH_INICIAL = "0" * 64


def _instante(valor: datetime) -> str:
    if valor.utcoffset() is None:
        raise TypeError("instante sem fuso na auditoria")
    return valor.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def normalizar(valor: object) -> Any:
    """Converte um valor para a forma canônica; recusa o que não tem forma estável."""
    if valor is None or isinstance(valor, bool | int | str):
        return valor
    if isinstance(valor, Enum):
        return normalizar(valor.value)
    if isinstance(valor, datetime):
        return _instante(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, Mapping):
        return {str(chave): normalizar(item) for chave, item in valor.items()}
    if isinstance(valor, list | tuple):
        return [normalizar(item) for item in valor]
    raise TypeError(f"valor sem forma canônica na auditoria: {type(valor).__name__}")


def json_canonico(valor: object) -> str:
    return json.dumps(normalizar(valor), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def serializar_alteracoes(alteracoes: Mapping[str, tuple[object, object]] | None) -> str | None:
    """`{campo: [antes, depois]}` como texto canônico (DD-10)."""
    if not alteracoes:
        return None
    return json_canonico({campo: list(par) for campo, par in alteracoes.items()})


def calcular_hash(hash_anterior: str, json_registro: str) -> str:
    return hashlib.sha256(f"{hash_anterior}\n{json_registro}".encode()).hexdigest()


def json_do_registro(
    *,
    id: int,
    instante: datetime,
    usuario_id: int | None,
    autorizador_id: int | None,
    operacao: str,
    entidade: str,
    entidade_id: str | None,
    alteracoes: str | None,
    motivo: str | None,
    origem: str | None,
    sessao_id: int | None,
    requisicao_id: str | None,
    versao_formato: int,
) -> str:
    return json_canonico(
        {
            "id": id,
            "instante": instante,
            "usuario_id": usuario_id,
            "autorizador_id": autorizador_id,
            "operacao": operacao,
            "entidade": entidade,
            "entidade_id": entidade_id,
            "alteracoes": alteracoes,
            "motivo": motivo,
            "origem": origem,
            "sessao_id": sessao_id,
            "requisicao_id": requisicao_id,
            "versao_formato": versao_formato,
        }
    )
