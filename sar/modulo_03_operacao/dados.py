"""Leituras comuns aos serviços do MOD-03: escalas, data de implantação, períodos com as vigências de alocação e
a tradução das restrições do banco. Os períodos vêm do MOD-02 pelo contrato de leitura (DDS §6.7)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from sar.modulo_02_cadastro.contrato import LeituraCadastro, PeriodoRef
from sar.modulo_03_operacao.compensacao import Periodo, Vigencia
from sar.modulo_03_operacao.contrato import Escala
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.nucleo.erros import RegraViolada
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import UnidadeDeTrabalho

# Duas gravações simultâneas que a verificação prévia não viu: a restrição do banco barra a segunda.
_RESTRICOES = {
    "uq_troca_pontual__origem": "troca.origem_repetida",
    "ck_troca_pontual__mesmo_mes": "P-11",
    "uq_extra_planejada__sessao": "extra.repetida",
}


def com_restricoes[R](chamada: Callable[[], R], restricoes: dict[str, str] | None = None) -> R:
    mapa = _RESTRICOES | (restricoes or {})
    try:
        return chamada()
    except Exception as erro:
        codigo = mapa.get(campos_do_erro(erro).get("restricao") or "")
        if codigo is not None:
            raise RegraViolada(codigo) from None
        raise


def escalas(uow: UnidadeDeTrabalho) -> dict[int, Escala]:
    """As seis escalas, por id (tabela fixa da 0002)."""
    return {
        e.id: Escala.de_texto(e.id, e.codigo, e.turno, e.dias, e.hora_inicio, e.hora_fim)
        for e in uow.repositorio(RepositorioOperacao).escalas()
    }


def implantacao(parametros: LeitorParametros) -> date | None:
    """Vazia: nenhuma sessão existe ainda (DD-91)."""
    valor = parametros.valor("data_implantacao")
    return valor if isinstance(valor, date) else None


def obito(periodos: Sequence[PeriodoRef]) -> date | None:
    return next((p.fim for p in periodos if p.obito), None)


def com_vigencias(
    uow: UnidadeDeTrabalho, periodos: Sequence[PeriodoRef], por_id: dict[int, Escala]
) -> tuple[Periodo, ...]:
    """Os períodos com as vigências de alocação de cada um (DD-27), para a lista esperada e a engine."""
    vigencias: dict[int, list[Vigencia]] = {}
    for a in uow.repositorio(RepositorioOperacao).alocacoes([p.id for p in periodos]):
        escala = por_id[a.escala_id] if a.escala_id is not None else None
        vigencias.setdefault(a.periodo_id, []).append(Vigencia(a.vigencia_inicio, escala))
    return tuple(Periodo(p.inicio, p.fim, tuple(vigencias.get(p.id, ()))) for p in periodos)


def periodos_de(
    uow: UnidadeDeTrabalho, leitura: LeituraCadastro, paciente_ids: Sequence[int] | None, por_id: dict[int, Escala]
) -> dict[int, tuple[tuple[Periodo, ...], date | None]]:
    """Para cada paciente vivo: os períodos com vigências e a data do óbito, se houver."""
    refs = leitura.periodos_de(uow, paciente_ids)
    todos = [p for lista in refs.values() for p in lista]
    montados = dict(zip((p.id for p in todos), com_vigencias(uow, todos, por_id), strict=True))
    return {pid: (tuple(montados[p.id] for p in lista), obito(lista)) for pid, lista in refs.items()}
