"""Linha de comando: erro de configuração na subida aparece por extenso, com o que fazer (DD-81 esconde só o texto dos
outros erros, que pode trazer SQL ou dado pessoal)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sar.cli import main


@pytest.mark.requisito("DD-34", "DD-85", "DD-81")
def test_worker_sem_ambiente_diz_o_que_falta(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for variavel in ("SAR_AMBIENTE", "SAR_COFRE", "SAR_QUARENTENA"):
        monkeypatch.delenv(variavel, raising=False)
    assert main(["worker"]) == 1
    erro = capsys.readouterr().err
    assert "SAR_COFRE e SAR_QUARENTENA são obrigatórias" in erro and "SAR_AMBIENTE=desenvolvimento" in erro


@pytest.mark.requisito("DD-81")
def test_segredo_ausente_diz_qual(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("SAR_SEGREDOS", str(tmp_path))
    assert main(["worker"]) == 1
    erro = capsys.readouterr().err
    assert f"segredo ausente: sar_worker em {tmp_path}" in erro and "SAR_SEGREDOS" in erro
