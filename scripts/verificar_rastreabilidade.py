"""Verifica a rastreabilidade entre a ERS e os testes (PT_recepcao §7).

Lê os requisitos da ERS, as marcas @pytest.mark.requisito(...) dos testes automatizados e a tabela de
verificação manual, e aponta:
  1. requisito com verificação por teste (coluna Verif. = T) sem teste automatizado;
  2. requisito sem verificação nenhuma;
  3. teste que cita requisito inexistente ou removido.

Uso:
  python verificar_rastreabilidade.py                    # relatório
  python verificar_rastreabilidade.py --estrito          # falha (código 1) se houver lacuna
  python verificar_rastreabilidade.py --estrito-citacoes # falha só no item 3 (CI até a homologação)
Opções: --ers caminho/da/ers.md  --testes pasta  --manual testes/verificacao_manual.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PREFIXOS = ("RF", "RNF", "SEG", "INV", "RN", "QAS", "DC")
ID = rf"(?:{'|'.join(PREFIXOS)})-\d+"
LINHA_REQUISITO = re.compile(rf"^\| ({ID}) \|(.*)$", re.M)
CITACAO = re.compile(rf"[\"']({ID})[\"']")
MARCA = re.compile(r"requisito\(([^)]*)\)")


def requisitos_da_ers(texto: str) -> dict[str, str]:
    """Devolve {id: método}, só das tabelas de requisitos (antes dos apêndices).

    O método é a coluna Verif. (T, I, A ou D) dos RF; para os demais, '?'.
    """
    corpo = texto.split("\n## Apêndice", 1)[0]
    requisitos: dict[str, str] = {}
    for ident, resto in LINHA_REQUISITO.findall(corpo):
        colunas = [c.strip() for c in resto.split("|")]
        metodo = colunas[1] if ident.startswith("RF-") and len(colunas) > 1 and colunas[1] in "TIAD" else "?"
        requisitos.setdefault(ident, metodo)
    return requisitos


def citacoes_nos_testes(pasta: Path) -> dict[str, set[str]]:
    """Devolve {id: {arquivos}} a partir das marcas requisito(...) dos testes."""
    achados: dict[str, set[str]] = {}
    for arquivo in sorted(pasta.rglob("*.py")):
        for marca in MARCA.findall(arquivo.read_text(encoding="utf-8")):
            for ident in CITACAO.findall(marca):
                achados.setdefault(ident, set()).add(str(arquivo))
    return achados


def verificacoes_manuais(arquivo: Path) -> set[str]:
    if not arquivo.exists():
        return set()
    return set(re.findall(rf"^\| ({ID}) \|", arquivo.read_text(encoding="utf-8"), re.M))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ers", default="docs/fase3-ers-v1_0.md")
    p.add_argument("--testes", default="testes")
    p.add_argument("--manual", default="testes/verificacao_manual.md")
    p.add_argument("--estrito", action="store_true")
    p.add_argument("--estrito-citacoes", action="store_true")
    a = p.parse_args()

    requisitos = requisitos_da_ers(Path(a.ers).read_text(encoding="utf-8"))
    automaticos = citacoes_nos_testes(Path(a.testes))
    manuais = verificacoes_manuais(Path(a.manual))

    t_sem_teste = sorted(r for r, m in requisitos.items() if m == "T" and r not in automaticos)
    sem_verificacao = sorted(
        r for r in requisitos if r not in automaticos and r not in manuais and r not in t_sem_teste
    )
    inexistentes = sorted(r for r in automaticos if r not in requisitos)

    total = len(requisitos)
    cobertos = sum(1 for r in requisitos if r in automaticos or r in manuais)
    print(f"Requisitos na ERS: {total}")
    print(
        f"Com verificação: {cobertos} ({100 * cobertos / total:.0f}%) — automática: "
        f"{sum(1 for r in requisitos if r in automaticos)}, manual: "
        f"{sum(1 for r in requisitos if r in manuais and r not in automaticos)}"
    )

    def listar(titulo: str, itens: list[str]) -> None:
        if itens:
            print(f"\n{titulo} ({len(itens)}):")
            for i in range(0, len(itens), 10):
                print("  " + ", ".join(itens[i : i + 10]))

    listar("Verificação por teste (T) sem teste automatizado", t_sem_teste)
    listar("Sem verificação nenhuma", sem_verificacao)
    listar("Citados em teste, mas inexistentes ou removidos na ERS", inexistentes)

    lacunas = len(t_sem_teste) + len(sem_verificacao) + len(inexistentes)
    if lacunas == 0:
        print("\nRastreabilidade completa.")
    if a.estrito and lacunas:
        return 1
    return 1 if (a.estrito_citacoes and inexistentes) else 0


if __name__ == "__main__":
    sys.exit(main())
