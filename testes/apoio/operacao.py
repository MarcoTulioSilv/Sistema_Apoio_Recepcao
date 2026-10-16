"""Apoio dos testes do MOD-03: as seis escalas da 0002 (DEC-52, P-14) e um construtor de instantes locais."""

from __future__ import annotations

from datetime import date, datetime, time

from sar.modulo_03_operacao.calendario import Antecedencias, Escala
from sar.modulo_08_dados.relogio import FUSO_CLINICA

ESCALAS = [
    Escala.de_texto(1, "1-seg", 1, "seg,qua,sex", time(6), time(10)),
    Escala.de_texto(2, "1-ter", 1, "ter,qui,sab", time(6), time(10)),
    Escala.de_texto(3, "2-seg", 2, "seg,qua,sex", time(11), time(15)),
    Escala.de_texto(4, "2-ter", 2, "ter,qui,sab", time(11), time(15)),
    Escala.de_texto(5, "3-seg", 3, "seg,qua,sex", time(16), time(20)),
    Escala.de_texto(6, "3-ter", 3, "ter,qui,sab", time(16), time(20)),
]
POR_CODIGO = {e.codigo: e for e in ESCALAS}
PADRAO = Antecedencias.em_minutos(60, 60)


def local(dia: date, hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    """Instante no fuso da clínica."""
    return datetime.combine(dia, time(hora, minuto, segundo), FUSO_CLINICA)
