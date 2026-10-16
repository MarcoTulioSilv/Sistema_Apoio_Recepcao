"""Classificação, pareamento e balanço do mês — `CompensacaoEngine` (DDS §7.4 a §7.6).

Puro, por paciente e por mês. O pareamento automático é recalculado a cada consulta; só as escolhas humanas
(ligações manuais e trocas pontuais) são gravadas (DD-25). Testado por propriedades (DD-29).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from sar.modulo_03_operacao.calendario import Sessao, competencia, limites_da_competencia
from sar.modulo_03_operacao.contrato import LIMITE_EXTRAS, Escala, OrigemPar


def _ordem(sessao: Sessao) -> tuple[date, int, int]:
    return (sessao.data, sessao.escala.turno, sessao.escala.id)


# ------------------------------------------------------------------ vagas previstas (§7.5, P-09, P-12)
@dataclass(frozen=True, slots=True)
class Vigencia:
    """Alocação só com início; o fim é a seguinte ou o fim do período; escala nula = sem alocação (DD-27)."""

    inicio: date
    escala: Escala | None


@dataclass(frozen=True, slots=True)
class Periodo:
    inicio: date
    fim: date | None  # data do evento de encerramento, que ainda conta como prevista (P-09)
    vigencias: tuple[Vigencia, ...] = ()

    def contem(self, data: date) -> bool:
        return self.inicio <= data and (self.fim is None or data <= self.fim)

    def escala_em(self, data: date) -> Escala | None:
        vigentes = [v for v in self.vigencias if v.inicio <= data]
        return max(vigentes, key=lambda v: v.inicio).escala if vigentes else None


def vagas_previstas(
    comp: str,
    periodos: Iterable[Periodo],
    implantacao: date | None,
    nao_realizadas: Iterable[tuple[date, int]] = (),
) -> list[Sessao]:
    """Vagas da escala vigente em cada data do mês, dentro do período, a partir da implantação, sem as sessões
    não realizadas (data, id da escala)."""
    if implantacao is None:  # DD-91
        return []
    fora = set(nao_realizadas)
    periodos = list(periodos)
    primeiro, ultimo = limites_da_competencia(comp)
    vagas = []
    for n in range((ultimo - primeiro).days + 1):
        dia = primeiro + timedelta(days=n)
        if dia < implantacao:
            continue
        for periodo in periodos:
            escala = periodo.escala_em(dia) if periodo.contem(dia) else None
            if escala is not None and escala.atende(dia) and (dia, escala.id) not in fora:
                vagas.append(Sessao(dia, escala))
    return sorted(set(vagas), key=_ordem)


# ------------------------------------------------------------------ entradas e saída da engine
@dataclass(frozen=True, slots=True)
class Marcacao:
    """Presença confirmada, ou resolvida pela lista esperada se a sessão ainda não foi confirmada."""

    sessao: Sessao
    presente: bool


@dataclass(frozen=True, slots=True)
class Troca:
    """Troca pontual não cancelada: a origem é a vaga do paciente nessa data (P-10, P-11)."""

    origem: date
    destino: Sessao


@dataclass(frozen=True, slots=True)
class Ligacao:
    """Par escolhido pela recepção (DD-25): a sessão da ausência e a da presença."""

    ausencia: Sessao
    presenca: Sessao


class Classificacao(StrEnum):
    REGULAR = "regular"
    AUSENCIA = "ausencia"
    TROCA = "troca"  # presença fora da escala compensando a origem da troca
    REPOSICAO = "reposicao"  # presença fora da escala em par manual ou automático
    EXTRA = "extra"  # presença fora da escala sem par


@dataclass(frozen=True, slots=True)
class Par:
    ausencia: Sessao
    presenca: Sessao
    origem: OrigemPar


@dataclass(frozen=True, slots=True)
class Balanco:
    """RF-916. Extras provisórias com o mês aberto, definitivas com o mês fechado."""

    previstas: int
    realizadas: int
    ausencias_nao_compensadas: int
    reposicoes: int
    extras: int
    a_realizar: int  # vagas ainda sem marcação: sessões futuras do mês
    provisorio: bool

    @property
    def aviso_extra(self) -> bool:
        """Acrescentar mais uma presença pede o aviso de RF-506; nunca bloqueia."""
        return self.extras >= LIMITE_EXTRAS

    @property
    def extra_alem_do_limite(self) -> bool:
        """Pendência "extra além do limite" (RN-01)."""
        return self.extras > LIMITE_EXTRAS


@dataclass(frozen=True, slots=True)
class Compensacao:
    competencia: str
    previstas: tuple[Sessao, ...]
    regulares: tuple[Sessao, ...]
    ausencias: tuple[Sessao, ...]
    fora_da_escala: tuple[Sessao, ...]
    pares: tuple[Par, ...]
    ligacoes_ignoradas: tuple[Ligacao, ...]  # deixaram de valer por alteração posterior; a tela informa
    a_realizar: tuple[Sessao, ...]
    _classes: dict[Sessao, Classificacao] = field(default_factory=dict, compare=False, repr=False)

    def classificacao(self, sessao: Sessao) -> Classificacao | None:
        return self._classes.get(sessao)

    @property
    def ausencias_livres(self) -> tuple[Sessao, ...]:
        pareadas = {p.ausencia for p in self.pares}
        return tuple(a for a in self.ausencias if a not in pareadas)

    @property
    def extras(self) -> tuple[Sessao, ...]:
        pareadas = {p.presenca for p in self.pares}
        return tuple(p for p in self.fora_da_escala if p not in pareadas)

    def balanco(self, mes_fechado: bool) -> Balanco:
        return Balanco(
            previstas=len(self.previstas),
            realizadas=len(self.regulares) + len(self.fora_da_escala),
            ausencias_nao_compensadas=len(self.ausencias_livres),
            reposicoes=len(self.pares),
            extras=len(self.extras),
            a_realizar=len(self.a_realizar),
            provisorio=not mes_fechado,
        )


# ------------------------------------------------------------------ a engine
def compensar(
    comp: str,
    previstas: Iterable[Sessao],
    marcacoes: Iterable[Marcacao],
    trocas: Iterable[Troca] = (),
    ligacoes: Iterable[Ligacao] = (),
) -> Compensacao:
    """Classifica e pareia o mês `comp`; o que for de outro mês é desconsiderado (pares só no mesmo mês)."""

    def do_mes(sessao: Sessao) -> bool:
        return competencia(sessao.data) == comp

    vagas = sorted({s for s in previstas if do_mes(s)}, key=_ordem)
    conjunto_vagas = set(vagas)
    por_sessao: dict[Sessao, bool] = {}
    for m in marcacoes:
        if do_mes(m.sessao):
            por_sessao[m.sessao] = m.presente
    regulares = [s for s in vagas if por_sessao.get(s) is True]
    ausencias = [s for s in vagas if por_sessao.get(s) is False]
    a_realizar = [s for s in vagas if s not in por_sessao]
    fora = sorted((s for s, presente in por_sessao.items() if presente and s not in conjunto_vagas), key=_ordem)

    ausencias_livres = set(ausencias)
    presencas_livres = set(fora)
    vaga_do_dia = {s.data: s for s in vagas}
    pares: list[Par] = []

    def parear(ausencia: Sessao, presenca: Sessao, origem: OrigemPar) -> None:
        ausencias_livres.discard(ausencia)
        presencas_livres.discard(presenca)
        pares.append(Par(ausencia, presenca, origem))

    # 1. Troca pontual: a origem foi ausência e o destino, presença.
    for troca in sorted(trocas, key=lambda t: (t.origem, _ordem(t.destino))):
        origem = vaga_do_dia.get(troca.origem)
        if origem is not None and origem in ausencias_livres and troca.destino in presencas_livres:
            parear(origem, troca.destino, OrigemPar.TROCA)

    # 2. Ligação manual, se os dois lados ainda valem.
    ignoradas: list[Ligacao] = []
    for ligacao in sorted(ligacoes, key=lambda li: (_ordem(li.ausencia), _ordem(li.presenca))):
        if not (do_mes(ligacao.ausencia) and do_mes(ligacao.presenca)):
            continue
        if ligacao.ausencia in ausencias_livres and ligacao.presenca in presencas_livres:
            parear(ligacao.ausencia, ligacao.presenca, OrigemPar.MANUAL)
        else:
            ignoradas.append(ligacao)

    # 3. Automático: a ausência livre mais antiga com a presença livre mais antiga (RF-918).
    for ausencia, presenca in zip(
        sorted(ausencias_livres, key=_ordem), sorted(presencas_livres, key=_ordem), strict=False
    ):
        parear(ausencia, presenca, OrigemPar.AUTOMATICO)

    pares.sort(key=lambda p: (_ordem(p.ausencia), _ordem(p.presenca)))
    classes: dict[Sessao, Classificacao] = {s: Classificacao.REGULAR for s in regulares}
    classes.update({s: Classificacao.AUSENCIA for s in ausencias})
    classes.update({s: Classificacao.EXTRA for s in fora})
    for par in pares:
        classes[par.presenca] = Classificacao.TROCA if par.origem is OrigemPar.TROCA else Classificacao.REPOSICAO
    return Compensacao(
        comp, tuple(vagas), tuple(regulares), tuple(ausencias), tuple(fora), tuple(pares), tuple(ignoradas),
        tuple(a_realizar), classes,
    )  # fmt: skip
