"""Gera dados/municipios_ibge.csv a partir da API pública de localidades do IBGE (RF-1205).

Formato esperado pela migração 0002: três colunas, codigo_ibge;nome;uf, com códigos de 7 dígitos.
É dado público, sem nenhum dado de paciente. Rodar de novo quando o IBGE criar ou renomear município.

Uso: python scripts/gerar_municipios_ibge.py [--saida dados/municipios_ibge.csv]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
MINIMO = 5570
GZIP = bytes((0x1F, 0x8B))


def baixar() -> list[dict[str, object]]:
    with urllib.request.urlopen(URL, timeout=60) as resposta:  # URL fixa, https
        corpo: bytes = resposta.read()
    if corpo[:2] == GZIP:  # a API responde em gzip mesmo sem pedido
        corpo = gzip.decompress(corpo)
    dados: list[dict[str, object]] = json.loads(corpo)
    return dados


def linhas(municipios: list[dict[str, object]]) -> list[tuple[str, str, str]]:
    resultado = []
    for m in municipios:
        codigo, nome, uf = str(m["municipio-id"]), str(m["municipio-nome"]).strip(), str(m["UF-sigla"])
        if not re.fullmatch(r"\d{7}", codigo) or not re.fullmatch(r"[A-Z]{2}", uf) or not nome:
            raise ValueError(f"município fora do formato: {codigo}")
        resultado.append((codigo, nome, uf))
    if len({c for c, _, _ in resultado}) != len(resultado):
        raise ValueError("código de município repetido")
    if len(resultado) < MINIMO:
        raise ValueError(f"só {len(resultado)} municípios; esperado ao menos {MINIMO}")
    return sorted(resultado)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--saida", default="dados/municipios_ibge.csv")
    a = p.parse_args()
    saida = Path(a.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    tabela = linhas(baixar())
    with saida.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=";", lineterminator="\n")
        escritor.writerow(("codigo_ibge", "nome", "uf"))
        escritor.writerows(tabela)
    print(f"{len(tabela)} municípios gravados em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
