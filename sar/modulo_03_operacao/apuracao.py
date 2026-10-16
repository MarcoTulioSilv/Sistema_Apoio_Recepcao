"""Reúne o que está gravado para as funções puras: a lista esperada de uma sessão (§7.2) e a compensação do mês
de vários pacientes de uma vez (§7.4), com poucas consultas (§11.3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.calendario import Sessao, limites_da_competencia, sessoes_entre
from sar.modulo_03_operacao.compensacao import Compensacao, Ligacao, Marcacao, Troca, compensar, vagas_previstas
from sar.modulo_03_operacao.contrato import Escala
from sar.modulo_03_operacao.lista_esperada import Esperado, SituacaoPaciente, lista_esperada
from sar.modulo_08_dados.interfaces.operacao import PresencaGravada, RepositorioOperacao, SessaoGravada
from sar.nucleo.uow import UnidadeDeTrabalho


def situacoes(
    uow: UnidadeDeTrabalho,
    leitura: LeituraCadastro,
    por_id: dict[int, Escala],
    paciente_ids: Sequence[int] | None,
    inicio: date,
    fim: date,
) -> dict[int, SituacaoPaciente]:
    """Períodos com vigências, óbito, trocas e extras de cada paciente vivo, com as trocas e extras entre as datas."""
    repositorio = uow.repositorio(RepositorioOperacao)
    periodos = dados.periodos_de(uow, leitura, paciente_ids, por_id)
    ids = list(periodos)
    trocas: dict[int, list[Troca]] = {}
    for t in repositorio.trocas(ids, inicio, fim):
        trocas.setdefault(t.paciente_id, []).append(
            Troca(t.data_origem, Sessao(t.data_destino, por_id[t.escala_destino_id]))
        )
    extras: dict[int, list[Sessao]] = {}
    for e in repositorio.extras(ids, inicio, fim):
        extras.setdefault(e.paciente_id, []).append(Sessao(e.data, por_id[e.escala_id]))
    return {
        pid: SituacaoPaciente(pid, lista, obito, tuple(trocas.get(pid, ())), tuple(extras.get(pid, ())))
        for pid, (lista, obito) in periodos.items()
    }


@dataclass(frozen=True, slots=True)
class ListaDaSessao:
    sessao: Sessao
    gravada: SessaoGravada | None
    itens: list[Esperado]
    excecoes: list[PresencaGravada]  # as linhas de presença gravadas na sessão


def lista_da_sessao(
    uow: UnidadeDeTrabalho, leitura: LeituraCadastro, sessao: Sessao, travar: bool = False
) -> ListaDaSessao:
    """Todo paciente da lista tem período que cobre a data (INV-04): os candidatos são esses."""
    repositorio = uow.repositorio(RepositorioOperacao)
    gravada = repositorio.sessao(sessao.data, sessao.escala.id, travar=travar)
    excecoes = repositorio.presencas_da_sessao(gravada.id) if gravada is not None else []
    candidatos = leitura.pacientes_com_periodo_aberto_em(uow, sessao.data)
    situacao = situacoes(uow, leitura, dados.escalas(uow), candidatos, sessao.data, sessao.data)
    marcadas = {p.paciente_id: p.situacao == "presente" for p in excecoes}
    return ListaDaSessao(sessao, gravada, lista_esperada(sessao, situacao.values(), marcadas), excecoes)


@dataclass(frozen=True, slots=True)
class Apurado:
    compensacao: Compensacao
    presencas: dict[Sessao, PresencaGravada]  # linhas gravadas do paciente no mês, por sessão


def apurar(
    uow: UnidadeDeTrabalho,
    leitura: LeituraCadastro,
    implantacao: date | None,
    comp: str,
    agora: datetime,
    paciente_ids: Sequence[int] | None,
) -> dict[int, Apurado]:
    """Compensação do mês de cada paciente. Sessão confirmada vale pelas presenças gravadas; sessão já começada e
    não confirmada, pela lista esperada com as exceções (§7.4); sessão ainda por começar fica a realizar."""
    repositorio = uow.repositorio(RepositorioOperacao)
    por_id = dados.escalas(uow)
    primeiro, ultimo = limites_da_competencia(comp)
    situacao = situacoes(uow, leitura, por_id, paciente_ids, primeiro, ultimo)
    ids = list(situacao)
    gravadas = {(s.data, s.escala_id): s for s in repositorio.sessoes(primeiro, ultimo)}
    nao_realizadas = [k for k, s in gravadas.items() if s.nao_realizada_motivo is not None]
    comecadas = [s for s in sessoes_entre(por_id.values(), primeiro, ultimo, implantacao) if s.inicio <= agora]

    linhas: dict[int, dict[Sessao, PresencaGravada]] = {pid: {} for pid in ids}
    por_presenca: dict[int, tuple[int, Sessao]] = {}
    for p in repositorio.presencas(ids, primeiro, ultimo):
        sessao = Sessao(p.data, por_id[p.escala_id])
        linhas[p.paciente_id][sessao] = p
        por_presenca[p.id] = (p.paciente_id, sessao)
    ligacoes: dict[int, list[Ligacao]] = {}
    for li in repositorio.ligacoes(list(por_presenca)):
        if li.ausencia_id in por_presenca and li.presenca_id in por_presenca:  # outro mês fica fora (pares no mês)
            dono, ausencia = por_presenca[li.ausencia_id]
            ligacoes.setdefault(dono, []).append(Ligacao(ausencia, por_presenca[li.presenca_id][1]))

    resultado = {}
    for pid in ids:
        paciente = situacao[pid]
        marcacoes = []
        for sessao in comecadas:
            gravada = gravadas.get((sessao.data, sessao.escala.id))
            linha = linhas[pid].get(sessao)
            if gravada is not None and gravada.nao_realizada_motivo is not None:
                continue
            if gravada is not None and gravada.confirmada_em is not None:
                if linha is not None:
                    marcacoes.append(Marcacao(sessao, linha.situacao == "presente"))
                continue
            excecao = {pid: linha.situacao == "presente"} if linha is not None else {}
            for item in lista_esperada(sessao, [paciente], excecao):
                marcacoes.append(Marcacao(sessao, item.presente))
        previstas = vagas_previstas(comp, paciente.periodos, implantacao, nao_realizadas)
        resultado[pid] = Apurado(
            compensar(comp, previstas, marcacoes, paciente.trocas, ligacoes.get(pid, ())), linhas[pid]
        )
    return resultado


def mes_fechado(uow: UnidadeDeTrabalho, implantacao: date | None, comp: str, hoje: date) -> tuple[bool, list[Sessao]]:
    """DD-26: terminou e todas as sessões dele estão confirmadas (ou registradas como não realizadas). Devolve
    também as sessões pendentes, para o relatório informar quantas faltam e quais (RF-913)."""
    por_id = dados.escalas(uow)
    primeiro, ultimo = limites_da_competencia(comp)
    confirmadas = {
        (s.data, s.escala_id)
        for s in uow.repositorio(RepositorioOperacao).sessoes(primeiro, ultimo)
        if s.confirmada_em is not None
    }
    pendentes = [
        s
        for s in sessoes_entre(por_id.values(), primeiro, min(ultimo, hoje), implantacao)
        if (s.data, s.escala.id) not in confirmadas
    ]
    return (hoje > ultimo and not pendentes), pendentes
