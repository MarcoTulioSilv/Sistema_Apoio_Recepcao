"""Linha de comando: erro de configuração na subida aparece por extenso, com o que fazer (DD-81 esconde só o texto dos
outros erros, que pode trazer SQL ou dado pessoal)."""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

from sar.cli import main


@pytest.mark.requisito("DD-34", "DD-85", "DD-81")
def test_worker_sem_ambiente_diz_o_que_falta(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for variavel in ("SAR_AMBIENTE", "SAR_COFRE", "SAR_QUARENTENA"):
        monkeypatch.delenv(variavel, raising=False)
    # Sem segredos, como no CI: antes, o segredo do banco era lido primeiro e escondia o que de fato faltava.
    monkeypatch.setenv("SAR_SEGREDOS", str(tmp_path))
    assert main(["worker"]) == 1
    erro = capsys.readouterr().err
    assert "SAR_COFRE e SAR_QUARENTENA são obrigatórias" in erro and "SAR_AMBIENTE=desenvolvimento" in erro


@pytest.mark.requisito("DD-81")
def test_segredo_ausente_diz_qual(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("SAR_SEGREDOS", str(tmp_path))
    monkeypatch.setenv("SAR_AMBIENTE", "desenvolvimento")  # as pastas passam; o que falta é o segredo
    assert main(["worker"]) == 1
    erro = capsys.readouterr().err
    assert f"segredo ausente: sar_worker em {tmp_path}" in erro and "SAR_SEGREDOS" in erro


def test_pacote_instalado_no_ambiente(tmp_path: Path) -> None:
    """O comando `sar` depende do pacote instalado (`pip install -e .`), não da pasta atual: os testes acham o `sar`
    pelo pythonpath do pytest e não perceberiam uma instalação quebrada pela metade."""
    ambiente = {chave: valor for chave, valor in os.environ.items() if chave != "PYTHONPATH"}
    importacao = subprocess.run(
        [sys.executable, "-c", "import sar.cli"], cwd=tmp_path, env=ambiente, capture_output=True, text=True,
        check=False,
    )  # fmt: skip
    assert importacao.returncode == 0, 'pacote sar não instalado: rode pip install -e ".[dev]" (docs/comandos.md)'
