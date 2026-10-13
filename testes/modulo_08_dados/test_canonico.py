"""CT-AUD-01, parte sem banco: a forma canônica da DDS §3.10."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sar.modulo_08_dados.canonico import (
    HASH_INICIAL,
    calcular_hash,
    json_canonico,
    json_do_registro,
    serializar_alteracoes,
)

CAMPOS_DDS = [  # §3.10, item 1
    "id",
    "instante",
    "usuario_id",
    "autorizador_id",
    "operacao",
    "entidade",
    "entidade_id",
    "alteracoes",
    "motivo",
    "origem",
    "sessao_id",
    "requisicao_id",
    "versao_formato",
]

valores = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=20),
    st.dates(),
    st.decimals(allow_nan=False, allow_infinity=False),
)


def registro(**mudancas: object) -> str:
    campos: dict[str, object] = {
        "id": 1,
        "instante": datetime(2026, 9, 30, 12, 0, 0, 123456, tzinfo=UTC),
        "usuario_id": 7,
        "autorizador_id": None,
        "operacao": "cadastro.paciente.atualizar",
        "entidade": "paciente",
        "entidade_id": "42",
        "alteracoes": None,
        "motivo": None,
        "origem": "10.0.0.5",
        "sessao_id": 3,
        "requisicao_id": "a" * 32,
        "versao_formato": 1,
    }
    campos.update(mudancas)
    return json_do_registro(**campos)  # type: ignore[arg-type]


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10")
@given(st.dictionaries(st.text(min_size=1, max_size=10), st.tuples(valores, valores), max_size=8))
def test_mesmas_alteracoes_em_qualquer_ordem_dao_o_mesmo_texto(alteracoes: dict[str, tuple[object, object]]) -> None:
    invertido = dict(reversed(list(alteracoes.items())))
    assert serializar_alteracoes(alteracoes) == serializar_alteracoes(invertido)


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10")
def test_json_do_registro_tem_exatamente_os_campos_da_dds_em_ordem_alfabetica() -> None:
    texto = registro()
    assert list(json.loads(texto)) == sorted(CAMPOS_DDS)
    assert ", " not in texto and ": " not in texto


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10")
def test_formatos_de_instante_data_decimal_e_texto() -> None:
    texto = json_canonico(
        {
            "instante": datetime(2026, 9, 30, 9, 15, 0, 5, tzinfo=timezone(timedelta(hours=-3))),
            "data": date(2026, 9, 30),
            "valor": Decimal("10.50"),
            "nome": "Conceição",
        }
    )
    assert texto == '{"data":"2026-09-30","instante":"2026-09-30T12:15:00.000005Z","nome":"Conceição","valor":"10.50"}'


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10")
@pytest.mark.parametrize("valor", [b"bytes", 1.5, datetime(2026, 9, 30, 12, 0), object()])  # noqa: DTZ001
def test_recusa_valor_sem_forma_canonica(valor: object) -> None:
    with pytest.raises(TypeError):
        serializar_alteracoes({"campo": (None, valor)})


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10")
def test_hash_e_sha256_do_anterior_quebra_de_linha_e_json() -> None:
    texto = registro()
    assert calcular_hash(HASH_INICIAL, texto) == hashlib.sha256(("0" * 64 + "\n" + texto).encode()).hexdigest()
    assert calcular_hash(HASH_INICIAL, texto) != calcular_hash(HASH_INICIAL, registro(motivo="outro"))


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10")
def test_alteracoes_entram_no_registro_como_o_texto_gravado() -> None:
    alteracoes = serializar_alteracoes({"nome": ("A", "B")})
    assert json.loads(registro(alteracoes=alteracoes))["alteracoes"] == '{"nome":["A","B"]}'
    assert serializar_alteracoes({}) is None
