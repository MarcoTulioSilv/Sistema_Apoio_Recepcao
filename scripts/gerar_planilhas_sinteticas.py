"""Gera as três planilhas sintéticas da carga inicial (PT §5.3) numa pasta, com os nomes que o `sar carga` espera.

Dados fictícios da fábrica dos testes (Faker pt_BR, todo nome termina em "Fictício"), na estrutura descrita no
perfilamento da fase 1 e com os defeitos reais conhecidos. Serve para ensaiar a simulação e a efetivação no banco
de desenvolvimento e na homologação. Nunca use planilha real para isso (CLAUDE.md, regra 1).

    python scripts/gerar_planilhas_sinteticas.py PASTA [--fichas 146] [--semente 7]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))  # a fábrica fica em testes/apoio

from testes.apoio import planilhas  # noqa: E402
from testes.apoio.fabrica import Fabrica  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planilhas sintéticas da carga inicial (PT §5.3)")
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--fichas", type=int, default=146, help="fichas da P1 (padrão: 146, como a base real)")
    parser.add_argument("--historicos", type=int, default=420, help="linhas da P4 fora da base (padrão: 420)")
    parser.add_argument("--semente", type=int, default=7)
    args = parser.parse_args(argv)
    gerado = planilhas.gerar(Fabrica(args.semente), args.fichas, args.historicos, args.semente)
    pasta = gerado.gravar(args.pasta)
    esperado = gerado.esperados()
    print(f"Planilhas em {pasta}:")
    print(f"  P1: {esperado['linhas']} fichas; esperadas {esperado['importados']} importadas e "
          f"{esperado['excecoes']} exceções")  # fmt: skip
    print(f"  P4: {gerado.linhas_p4} linhas ({gerado.fora_da_base_p4} históricas e {gerado.sem_prontuario_p4} sem "
          f"prontuário)")  # fmt: skip
    print(f"  P3: {gerado.linhas_p3} eventos ({gerado.casadas_p3} de paciente ainda listado na P1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
