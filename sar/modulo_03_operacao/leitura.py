"""Leituras do MOD-03 para os outros módulos (DDS §7.10): o MOD-05 (relatório mensal, RF-913 a RF-915) e o MOD-07."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.apuracao import apurar, mes_fechado
from sar.modulo_03_operacao.calendario import DEVIDAS, estado, limites_da_competencia, sessoes_entre
from sar.modulo_03_operacao.contrato import EstadoSessao, MarcaAlteracao, PareamentoDoMes, ResumoSessao, SituacaoDoMes
from sar.modulo_03_operacao.frequencia import montar_pareamento
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import UnidadeDeTrabalho


class ServicoLeituraOperacao:
    """Implementa a LeituraOperacao do contrato."""

    def __init__(self, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._leitura = leitura
        self._parametros = parametros

    def mes_fechado(self, uow: UnidadeDeTrabalho, competencia: str, hoje: date) -> SituacaoDoMes:
        fechado, pendentes = mes_fechado(uow, dados.implantacao(self._parametros), competencia, hoje)
        return SituacaoDoMes(fechado, tuple(ResumoSessao(s.data, s.escala, EstadoSessao.DEVIDA) for s in pendentes))

    def sessoes_nao_confirmadas(
        self, uow: UnidadeDeTrabalho, inicio: date, fim: date, agora: datetime
    ) -> list[ResumoSessao]:
        implantacao = dados.implantacao(self._parametros)
        antecedencias = dados.antecedencias(self._parametros)
        gravadas = {(s.data, s.escala_id): s for s in uow.repositorio(RepositorioOperacao).sessoes(inicio, fim)}
        resumos = []
        for sessao in sessoes_entre(dados.escalas(uow).values(), inicio, fim, implantacao):
            gravada = gravadas.get((sessao.data, sessao.escala.id))
            if gravada is not None and gravada.confirmada_em is not None:
                continue
            situacao = estado(sessao, agora, antecedencias)
            if situacao in DEVIDAS:
                resumos.append(ResumoSessao(sessao.data, sessao.escala, situacao))
        return resumos

    def marcas_alteracao(self, uow: UnidadeDeTrabalho, competencias: Sequence[str]) -> list[MarcaAlteracao]:
        return [
            MarcaAlteracao(m.competencia, m.instante, m.responsavel_id, m.autorizador_id, m.motivo)
            for m in uow.repositorio(RepositorioOperacao).marcas(competencias)
        ]

    def frequencia_do_mes(
        self, uow: UnidadeDeTrabalho, competencia: str, agora: datetime
    ) -> dict[int, PareamentoDoMes]:
        primeiro, ultimo = limites_da_competencia(competencia)
        implantacao = dados.implantacao(self._parametros)
        fechado = mes_fechado(uow, implantacao, competencia, agora.astimezone(FUSO_CLINICA).date())[0]
        no_mes = sorted(
            pid
            for pid, periodos in self._leitura.periodos_de(uow, None).items()
            if any(p.inicio <= ultimo and (p.fim is None or p.fim >= primeiro) for p in periodos)
        )
        apurados = apurar(uow, self._leitura, implantacao, competencia, agora, no_mes)
        return {pid: montar_pareamento(competencia, apurado, fechado) for pid, apurado in apurados.items()}
