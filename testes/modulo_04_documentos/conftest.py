"""Fixtures do MOD-04: um Tesseract falso, para a extração rodar sem o programa instalado, e a falta dele."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from testes.apoio.fabrica import Fabrica, PacienteFicticio


@pytest.fixture
def tesseract_falso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PacienteFicticio:
    """Um "Tesseract" que devolve sempre o mesmo texto, com o CPF e o CNS do paciente fictício e uma frase que nunca
    pode ser guardada. Vale também para o subprocesso, que herda SAR_TESSERACT."""
    paciente = Fabrica(7).paciente()
    texto = f"Paciente {paciente.nome}\nCPF {paciente.cpf}\nCNS {paciente.cns}\nDIAGNOSTICO SIGILOSO\n"
    script = tmp_path / "tesseract_falso.py"
    script.write_text(f"import sys\nsys.stdin.buffer.read()\nsys.stdout.write({texto!r})\n", encoding="utf-8")
    if sys.platform == "win32":
        programa = tmp_path / "tesseract.cmd"
        programa.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        programa = tmp_path / "tesseract"
        programa.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        programa.chmod(0o755)
    monkeypatch.setenv("SAR_TESSERACT", str(programa))
    return paciente


@pytest.fixture
def sem_tesseract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAR_TESSERACT", str(tmp_path / "nao-existe"))
