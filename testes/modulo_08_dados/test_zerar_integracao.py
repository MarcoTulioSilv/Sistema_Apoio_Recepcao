"""Recomeço do banco de desenvolvimento (comandos.md, seção 4): o reverter recusa banco com dados, e o
zerar-desenvolvimento apaga os dados de uso mantendo a estrutura, os dados fixos e os usuários.

Visto no uso (17 e 18/11/2026): `sar reverter base` com pacientes parava na 0002 depois de apagar as colunas da 0003,
e o `sar migrar` seguinte não as recriava; toda tela quebrava."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from sar.cli import main
from sar.modulo_08_dados import cli as banco
from testes.apoio.cadastro import INICIO, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica

pytestmark = pytest.mark.integracao


def contar(engine: Engine, sql: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(sql)).scalar_one())


@pytest.mark.requisito("DD-60")
def test_reverter_recusa_banco_com_dados_antes_de_mexer_na_estrutura(
    cadastro_zerado: dict[str, int],
    engine_web: Engine,
    fabrica: Fabrica,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    montar(engine_web).pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), INICIO)

    def nao_pode(*_args: object, **_kw: object) -> None:
        raise AssertionError("a reversão começou com o banco cheio")

    monkeypatch.setattr(banco.command, "downgrade", nao_pode)
    assert main(["reverter", "base"]) == 1
    assert "sar zerar-desenvolvimento --confirmo" in capsys.readouterr().err


@pytest.mark.requisito("DD-60", "DD-85")
def test_zerar_desenvolvimento_apaga_os_dados_e_mantem_usuarios_e_dados_fixos(
    cadastro_zerado: dict[str, int],
    engine_web: Engine,
    engine_migracao: Engine,
    fabrica: Fabrica,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    montar(engine_web).pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), INICIO)
    cofre, quarentena = tmp_path / "cofre", tmp_path / "quarentena"
    (cofre / "ab").mkdir(parents=True)
    (cofre / "ab" / "documento.bin").write_bytes(b"cifrado")
    quarentena.mkdir()
    monkeypatch.setenv("SAR_COFRE", str(cofre))
    monkeypatch.setenv("SAR_QUARENTENA", str(quarentena))
    usuarios = contar(engine_migracao, "SELECT COUNT(*) FROM usuario")
    municipios = contar(engine_migracao, "SELECT COUNT(*) FROM municipio")

    monkeypatch.setenv("SAR_AMBIENTE", "producao")
    assert main(["zerar-desenvolvimento", "--confirmo"]) == 1  # nunca fora do desenvolvimento
    monkeypatch.setenv("SAR_AMBIENTE", "desenvolvimento")
    assert main(["zerar-desenvolvimento"]) == 1  # sem confirmar
    assert contar(engine_migracao, "SELECT COUNT(*) FROM paciente") == 1
    capsys.readouterr()

    assert main(["zerar-desenvolvimento", "--confirmo"]) == 0
    for tabela in ("paciente", "periodo_tratamento", "auditoria", "sessao_usuario", "carga_lote"):
        assert contar(engine_migracao, f"SELECT COUNT(*) FROM {tabela}") == 0, tabela  # noqa: S608 — nome fixo
    assert contar(engine_migracao, "SELECT COUNT(*) FROM usuario") == usuarios
    assert contar(engine_migracao, "SELECT COUNT(*) FROM municipio") == municipios
    assert contar(engine_migracao, "SELECT ultimo_registro_id FROM auditoria_cabeca") == 0
    assert not any(cofre.rglob("*.bin"))
    assert "1 arquivo(s) do cofre e da quarentena" in capsys.readouterr().out
