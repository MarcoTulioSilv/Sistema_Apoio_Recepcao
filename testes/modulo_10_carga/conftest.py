"""Apoio dos testes do MOD-10: o serviço montado como no compor_carga, o contexto do TI e as planilhas sintéticas."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from sar.composicao import SemCep, montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_02_cadastro.servicos import ServicoLeituraCadastro, ServicoPacientes
from sar.modulo_06_configuracao.servicos import ServicoReferencias
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_10_carga.servicos import ServicoCarga
from sar.nucleo.contexto import Contexto, Perfil
from testes.apoio import planilhas
from testes.apoio.cadastro import AGORA
from testes.apoio.fabrica import Fabrica

CHAVE = bytes(range(32))


def sortear_os_primeiros(ids: list[int], quantos: int) -> list[int]:
    return sorted(ids)[:quantos]


def servico(engine: Engine) -> ServicoCarga:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    auditoria = ServicoAuditoria()
    referencias = ServicoReferencias()
    pacientes = ServicoPacientes(executar, auditoria, referencias, SemCep())
    leitura = ServicoLeituraCadastro()
    return ServicoCarga(
        executar, auditoria, pacientes, referencias, CifraAesGcm(CHAVE), pacientes, leitura, sortear_os_primeiros
    )


def ti(usuarios: dict[str, int]) -> Contexto:
    return Contexto(usuarios["ti"], Perfil.TI, None, "cli.carga", AGORA, "e" * 32)


@pytest.fixture
def carga(cadastro_zerado: dict[str, int], trilha_zerada: Engine) -> Iterator[dict[str, int]]:
    """Cadastro vazio e o convênio da ficha que não é SUS (IPASGO), como a administração teria cadastrado."""
    with trilha_zerada.begin() as c:
        c.execute(text("INSERT INTO convenio (nome, ativo) VALUES ('IPASGO', 1)"))
    yield cadastro_zerado


@pytest.fixture
def sinteticas(fabrica: Fabrica, tmp_path: Path) -> tuple[planilhas.Sinteticas, Path]:
    gerado = planilhas.gerar(fabrica)
    return gerado, gerado.gravar(tmp_path / "carga")


def contar(engine: Engine, sql: str, **parametros: object) -> int:
    with engine.connect() as c:
        return int(c.execute(text(sql), parametros).scalar_one())
