from __future__ import annotations

from pathlib import Path

import pytest

from sar.modulo_08_dados.banco import ConfigBanco
from sar.modulo_08_dados.segredos import ler_segredo


@pytest.fixture
def segredos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SAR_SEGREDOS", str(tmp_path))
    return tmp_path


@pytest.mark.requisito("DD-58")
def test_le_segredo_sem_espacos_nas_pontas(segredos: Path) -> None:
    (segredos / "sar_web").write_text("  senha-do-web\n", encoding="utf-8")
    assert ler_segredo("sar_web") == "senha-do-web"


@pytest.mark.requisito("DD-58")
def test_segredo_ausente_ou_vazio_falha_citando_so_o_nome(segredos: Path) -> None:
    with pytest.raises(RuntimeError, match="sar_web"):
        ler_segredo("sar_web")
    (segredos / "sar_web").write_text("\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="vazio"):
        ler_segredo("sar_web")


@pytest.mark.requisito("DD-58")
@pytest.mark.parametrize("nome", ["../fora", "SAR", "sar/web", ""])
def test_recusa_nome_que_sairia_da_pasta(segredos: Path, nome: str) -> None:
    with pytest.raises(ValueError):
        ler_segredo(nome)


@pytest.mark.requisito("DD-58", "RNF-624")
def test_configuracao_do_banco_nao_expoe_a_senha(segredos: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (segredos / "sar_web").write_text("Segredo-Do-Web-123", encoding="utf-8")
    monkeypatch.setenv("SAR_BANCO_HOST", "banco")
    monkeypatch.setenv("SAR_BANCO_PORTA", "3310")
    config = ConfigBanco.do_ambiente("sar_web")
    assert (config.usuario, config.host, config.porta, config.nome) == ("sar_web", "banco", 3310, "sar")
    assert "Segredo-Do-Web-123" not in repr(config)
    assert "Segredo-Do-Web-123" not in str(config.url())
