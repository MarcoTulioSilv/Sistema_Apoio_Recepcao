from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verificar_rastreabilidade.py"
ERS = """| ID | Requisito | Verif. | Origem |
|---|---|---|---|
| RF-001 | Fazer algo | T | B1 |
| RF-002 | Mostrar algo | D | B1 |
"""


def marca(ident: str) -> str:
    """Marca de teste montada em partes, para a varredura deste repositório não confundir o exemplo com uma
    citação de verdade."""
    return "@pytest.mark." + "requisito" + '("' + ident + '")\n'


def rodar(tmp_path: Path, teste: str, *opcoes: str) -> int:
    (tmp_path / "ers.md").write_text(ERS, encoding="utf-8")
    pasta = tmp_path / "testes"
    pasta.mkdir()
    (pasta / "test_x.py").write_text(teste, encoding="utf-8")
    args = [sys.executable, str(SCRIPT), "--ers", str(tmp_path / "ers.md"), "--testes", str(pasta), *opcoes]
    return subprocess.run(args, capture_output=True, check=False).returncode  # noqa: S603 — script do projeto


@pytest.mark.requisito("PT-7")
def test_estrito_citacoes_tolera_lacuna(tmp_path: Path) -> None:
    assert rodar(tmp_path, marca("RF-001"), "--estrito-citacoes") == 0


@pytest.mark.requisito("PT-7")
def test_estrito_citacoes_falha_com_requisito_inexistente(tmp_path: Path) -> None:
    assert rodar(tmp_path, marca("RF-999"), "--estrito-citacoes") == 1


@pytest.mark.requisito("PT-7")
def test_estrito_falha_com_lacuna(tmp_path: Path) -> None:
    assert rodar(tmp_path, marca("RF-001"), "--estrito") == 1
