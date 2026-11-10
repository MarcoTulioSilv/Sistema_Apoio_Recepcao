"""Regras puras da emissão: formatos dos valores que entram nos modelos, sem depender da localidade do sistema
operacional (RF-803)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")  # fmt: skip
FUSO = ZoneInfo("America/Sao_Paulo")
TURNOS = {1: "primeiro", 2: "segundo", 3: "terceiro"}  # DD-75: na interface e nos documentos, nunca o código


def data_extenso(municipio: str, data: date) -> str:
    """RF-803: "Jataí, 4 de novembro de 2026"; o primeiro dia do mês sai como "1º"."""
    dia = "1º" if data.day == 1 else str(data.day)
    return f"{municipio}, {dia} de {MESES[data.month - 1]} de {data.year}"


def data_curta(data: date | None) -> str:
    return data.strftime("%d/%m/%Y") if data is not None else ""


def turno(numero: int) -> str:
    return TURNOS[numero]


def cep(digitos: str) -> str:
    return f"{digitos[:5]}-{digitos[5:]}" if len(digitos) == 8 else digitos


def telefone(digitos: str | None) -> str:
    """(64) 3600-0000 ou (64) 99999-0000."""
    if not digitos:
        return ""
    ddd, numero = digitos[:2], digitos[2:]
    return f"({ddd}) {numero[:-4]}-{numero[-4:]}"


def cnpj(digitos: str | None) -> str:
    if not digitos:
        return ""
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def codigo_integridade(registro_id: int, codigo: str, registrada_em: datetime) -> str:
    """DD-86: o código da âncora mais recente, o número do registro e a data, em data local da clínica."""
    return f"{codigo} · nº {registro_id} · {registrada_em.astimezone(FUSO).strftime('%d/%m/%Y')}"


def competencia(instante: datetime) -> str:
    """AAAA-MM da data local da clínica."""
    return instante.astimezone(FUSO).strftime("%Y-%m")


def hoje(instante: datetime) -> date:
    return instante.astimezone(FUSO).date()
