"""Leituras do MOD-03 para os outros módulos (DDS §7.10): o MOD-05 (relatório mensal, RF-913 a RF-915) e o MOD-07."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.apuracao import apurar, mes_fechado
from sar.modulo_03_operacao.calendario import DEVIDAS, estado, limites_da_competencia, sessoes_entre
from sar.modulo_03_operacao.contrato import (
    ContagemEscalas,
    Escala,
    EstadoSessao,
    MarcaAlteracao,
    PareamentoDoMes,
    ResumoSessao,
    SituacaoDoMes,
    TrocaParaDocumento,
)
from sar.modulo_03_operacao.escalas import alocacao_vigente, contar_por_escala
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

    def troca(self, uow: UnidadeDeTrabalho, troca_id: int) -> TrocaParaDocumento | None:
        gravada = uow.repositorio(RepositorioOperacao).troca_por_id(troca_id)
        if gravada is None or gravada.cancelada_em is not None:
            return None
        if self._leitura.identificacao(uow, gravada.paciente_id) is None:  # anulado
            return None
        escalas = dados.escalas(uow)
        return TrocaParaDocumento(
            gravada.paciente_id,
            gravada.data_origem,
            self.turno_em(uow, gravada.paciente_id, gravada.data_origem),
            gravada.data_destino,
            escalas[gravada.escala_destino_id].turno,
        )

    def turno_em(self, uow: UnidadeDeTrabalho, paciente_id: int, data: date) -> int | None:
        periodo = self._leitura.periodo_aberto_em(uow, paciente_id, data)
        if periodo is None:
            return None
        vigente = alocacao_vigente(uow.repositorio(RepositorioOperacao).alocacoes([periodo.id]), data)
        if vigente is None or vigente.escala_id is None:
            return None
        return dados.escalas(uow)[vigente.escala_id].turno

    def escalas(self, uow: UnidadeDeTrabalho) -> list[Escala]:
        return sorted(dados.escalas(uow).values(), key=lambda e: (e.turno, min(e.dias)))

    def contagem(self, uow: UnidadeDeTrabalho, data: date) -> ContagemEscalas:
        return contar_por_escala(uow, self._leitura, data)

    def realizadas(self, uow: UnidadeDeTrabalho, inicio: date, fim: date) -> dict[int, int]:
        contagem: dict[int, int] = {}
        for presenca in uow.repositorio(RepositorioOperacao).presencas(None, inicio, fim):
            if presenca.situacao == "presente":
                contagem[presenca.paciente_id] = contagem.get(presenca.paciente_id, 0) + 1
        vivos = self._leitura.identificacoes(uow, sorted(contagem))
        return {pid: n for pid, n in contagem.items() if pid in vivos}

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
