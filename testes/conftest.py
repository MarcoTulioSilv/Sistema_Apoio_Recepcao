"""Fixtures comuns. Em desenvolvimento, os segredos ficam em segredos/ e o MySQL do compose na porta 3307;
no CI, as variáveis SAR_SEGREDOS e SAR_BANCO_PORTA vêm do workflow."""

from __future__ import annotations

import logging
import os
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.nucleo.logs import RUIDOSOS
from testes.apoio.fabrica import VALORES_SENSIVEIS, Fabrica
from testes.apoio.relogio_controlado import RelogioControlado
from testes.apoio.vazamento import ColetorLogs, vazamentos

RAIZ = Path(__file__).resolve().parent.parent
os.environ.setdefault("SAR_SEGREDOS", str(RAIZ / "segredos"))
os.environ.setdefault("SAR_BANCO_PORTA", "3307")


@pytest.fixture
def relogio() -> RelogioControlado:
    """Quarta-feira, 30/09/2026, 09:15 em Jataí — a cena do protótipo."""
    return RelogioControlado(datetime(2026, 9, 30, 12, 15, tzinfo=UTC))


@pytest.fixture
def fabrica(request: pytest.FixtureRequest) -> Fabrica:
    """Semente derivada do nome do teste: dados reprodutíveis e independentes entre testes."""
    return Fabrica(zlib.crc32(request.node.nodeid.encode()))


@pytest.fixture(scope="session")
def engine_migracao() -> Iterator[Engine]:
    """Banco de teste já migrado, pelo usuário de migração (pode criar as tabelas de apoio dos testes)."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_migracao"))
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def sem_dado_de_paciente_nos_logs() -> Iterator[None]:
    """CT-LOG-01 (RNF-624, DD-81): todo teste roda com os logs capturados no formato de produção; o teste
    falha se algum valor sensível gerado pela fábrica aparecer neles."""
    raiz = logging.getLogger()
    coletor = ColetorLogs()
    nivel_anterior = raiz.level
    raiz.addHandler(coletor)
    raiz.setLevel(logging.INFO)
    ruidosos = {nome: logging.getLogger(nome).level for nome in RUIDOSOS}
    for nome in RUIDOSOS:
        logging.getLogger(nome).setLevel(logging.WARNING)
    try:
        yield
    finally:
        raiz.removeHandler(coletor)
        raiz.setLevel(nivel_anterior)
        for nome, nivel in ruidosos.items():
            logging.getLogger(nome).setLevel(nivel)
    achados = vazamentos(coletor.linhas, VALORES_SENSIVEIS)
    assert not achados, f"CT-LOG-01: dado fictício de paciente apareceu no log: {achados}"
