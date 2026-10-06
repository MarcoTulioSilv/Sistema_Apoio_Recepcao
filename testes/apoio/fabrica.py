"""Fábrica de dados fictícios (PT §5.1). Nenhum dado real de paciente, nunca.

- Faker pt_BR, com semente: o mesmo teste gera sempre os mesmos dados.
- CPF e CNS válidos, gerados por algoritmo.
- Municípios de Goiás reais, da tabela do IBGE (dados/municipios_ibge.csv).
- Todo nome termina com o sobrenome "Fictício", que não pode coincidir com ninguém da base real.
- Todo valor sensível gerado fica em VALORES_SENSIVEIS, que o CT-LOG-01 procura nos logs.

Cada incremento acrescenta aqui os construtores das entidades que entrega.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from faker import Faker

MARCA = "Fictício"
CSV_MUNICIPIOS = Path(__file__).resolve().parents[2] / "dados" / "municipios_ibge.csv"
VALORES_SENSIVEIS: set[str] = set()


def _sensivel(valor: str) -> str:
    VALORES_SENSIVEIS.add(valor)
    return valor


@dataclass(frozen=True, slots=True)
class Municipio:
    codigo_ibge: str
    nome: str
    uf: str


@dataclass(frozen=True, slots=True)
class PacienteFicticio:
    nome: str
    nome_mae: str
    data_nascimento: date
    prontuario: str
    cpf: str
    cns: str
    municipio: Municipio


@cache
def municipios_go() -> tuple[Municipio, ...]:
    with CSV_MUNICIPIOS.open(encoding="utf-8", newline="") as f:
        linhas = csv.DictReader(f, delimiter=";")
        return tuple(Municipio(m["codigo_ibge"], m["nome"], m["uf"]) for m in linhas if m["uf"] == "GO")


def digitos_cpf(base: str) -> str:
    """Os dois dígitos verificadores do CPF para os nove primeiros dígitos."""
    numeros = [int(d) for d in base]
    for peso_inicial in (10, 11):
        soma = sum(d * p for d, p in zip(numeros, range(peso_inicial, 1, -1), strict=False))
        resto = soma * 10 % 11
        numeros.append(0 if resto == 10 else resto)
    return "".join(map(str, numeros[9:]))


def cns_definitivo(pis: str) -> str:
    """CNS definitivo (iniciado em 1 ou 2) a partir dos 11 primeiros dígitos, pelo algoritmo do DATASUS."""
    soma = sum(int(d) * p for d, p in zip(pis, range(15, 4, -1), strict=True))
    dv = 11 - soma % 11
    if dv == 11:
        dv = 0
    if dv == 10:
        soma += 2
        dv = 11 - soma % 11
        return f"{pis}001{dv}"
    return f"{pis}000{dv}"


class Fabrica:
    def __init__(self, semente: int) -> None:
        self._aleatorio = random.Random(semente)  # noqa: S311 — dados de teste, não criptografia
        self._faker = Faker("pt_BR")
        self._faker.seed_instance(semente)

    def nome(self) -> str:
        return _sensivel(f"{self._faker.first_name()} {self._faker.last_name()} {MARCA}")

    def cpf(self) -> str:
        while True:
            base = "".join(str(self._aleatorio.randrange(10)) for _ in range(9))
            if len(set(base)) > 1:  # sequências repetidas são inválidas
                return _sensivel(base + digitos_cpf(base))

    def cns(self) -> str:
        pis = str(self._aleatorio.choice((1, 2))) + "".join(str(self._aleatorio.randrange(10)) for _ in range(10))
        return _sensivel(cns_definitivo(pis))

    def prontuario(self) -> str:
        return f"F{self._aleatorio.randrange(10**6):06d}"

    def municipio_go(self) -> Municipio:
        return self._aleatorio.choice(municipios_go())

    def paciente(self) -> PacienteFicticio:
        return PacienteFicticio(
            nome=self.nome(),
            nome_mae=_sensivel(f"{self._faker.first_name_female()} {self._faker.last_name()} {MARCA}"),
            data_nascimento=self._faker.date_of_birth(minimum_age=18, maximum_age=95),
            prontuario=self.prontuario(),
            cpf=self.cpf(),
            cns=self.cns(),
            municipio=self.municipio_go(),
        )
