"""Gera os segredos do ambiente de desenvolvimento em segredos/ (ver segredos/LEIA-ME.md).

Valores aleatórios; nunca sobrescreve um arquivo existente. Não usar em produção.
"""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent / "segredos"
SENHAS = ("mysql_root", "sar_migracao", "sar_web", "sar_worker", "sar_expurgo")


def main() -> int:
    PASTA.mkdir(exist_ok=True)
    valores = {nome: secrets.token_urlsafe(24) for nome in SENHAS}
    valores["chave_mestra"] = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    for nome, valor in valores.items():
        arquivo = PASTA / nome
        if arquivo.exists():
            print(f"mantido  {nome}")
            continue
        arquivo.write_text(valor, encoding="ascii", newline="")
        print(f"criado   {nome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
