"""Pendências da operação (DDS §11.1, linhas 4 a 8; DD-54). O MOD-07 agrega; cada fonte responde ao conjunto numa
consulta só (§11.3) e devolve nada para o perfil que não vê a linha, mesmo antes do filtro do MOD-07, para que
dado de paciente nunca chegue ao TI (RNF-625)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.apuracao import apurar
from sar.modulo_03_operacao.calendario import (
    DEVIDAS,
    Sessao,
    competencia,
    estado,
    limites_da_competencia,
    sessoes_entre,
)
from sar.modulo_03_operacao.contrato import LIMITE_EXTRAS
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import FontePendencia, ItemPendencia, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho

R, A, E = Perfil.RECEPCAO, Perfil.ADMINISTRACAO, Perfil.ENFERMAGEM


def _hoje(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO_CLINICA).date()


def _no_inicio(data: date) -> datetime:
    return datetime.combine(data, time(), FUSO_CLINICA).astimezone(UTC)


def _ficha(paciente_id: int) -> str:
    return f"/pacientes/{paciente_id}"


class _Fonte:
    codigo: str
    prioridade: Prioridade
    perfis: frozenset[Perfil]
    de_paciente = True

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        return self._itens(uow, contexto, None) if contexto.perfil in self.perfis else []

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        if not self.de_paciente or contexto.perfil not in self.perfis or not paciente_ids:
            return []
        return self._itens(uow, contexto, paciente_ids)

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        raise NotImplementedError

    def _item(self, desde: datetime, descricao: str, paciente_id: int | None, destino: str) -> ItemPendencia:
        return ItemPendencia(self.codigo, self.prioridade, desde, descricao, destino, paciente_id)


class FonteSessaoNaoConfirmada(_Fonte):
    """Linha 4: sessão já terminada ou em curso, ainda sem confirmação; urgência (DD-23, DD-32). Sem paciente."""

    codigo = "sessao_nao_confirmada"
    prioridade = Prioridade.URGENCIA
    perfis = frozenset({R, A})
    de_paciente = False

    def __init__(self, parametros: LeitorParametros) -> None:
        self._parametros = parametros

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        implantacao = dados.implantacao(self._parametros)
        if implantacao is None:  # DD-91
            return []
        antecedencias = dados.antecedencias(self._parametros)
        hoje = _hoje(contexto)
        gravadas = {(s.data, s.escala_id): s for s in uow.repositorio(RepositorioOperacao).sessoes(implantacao, hoje)}
        itens = []
        for sessao in sessoes_entre(dados.escalas(uow).values(), implantacao, hoje, implantacao):
            gravada = gravadas.get((sessao.data, sessao.escala.id))
            if gravada is not None and gravada.confirmada_em is not None:
                continue
            if estado(sessao, contexto.instante, antecedencias) in DEVIDAS:
                descricao = f"{sessao.escala.rotulo} de {sessao.data:%d/%m/%Y} sem confirmação"
                itens.append(self._item(sessao.inicio.astimezone(UTC), descricao, None, "/"))
        return itens


class FonteSemAlocacao(_Fonte):
    """Linha 6: paciente em tratamento sem escala vigente (RF-403), nunca tratado como alocado por omissão."""

    codigo = "sem_alocacao"
    prioridade = Prioridade.ALTA
    perfis = frozenset({R, A, E})

    def __init__(self, leitura: LeituraCadastro) -> None:
        self._leitura = leitura

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        hoje = _hoje(contexto)
        em_tratamento = self._leitura.pacientes_com_periodo_aberto_em(uow, hoje)
        alvo = [p for p in em_tratamento if ids is None or p in set(ids)]
        itens = []
        for pid, (periodos, _) in dados.periodos_de(uow, self._leitura, alvo, dados.escalas(uow)).items():
            periodo = next((p for p in periodos if p.contem(hoje)), None)
            if periodo is None or periodo.escala_em(hoje) is not None:
                continue
            sem_desde = max([v.inicio for v in periodo.vigencias if v.inicio <= hoje] + [periodo.inicio])
            itens.append(self._item(_no_inicio(sem_desde), "Sem escala de diálise", pid, _ficha(pid)))
        return itens


class FonteTermoAEmitir(_Fonte):
    """Linha 5: termo da troca (DOC-03) ou da extra do mês (DOC-07) ainda sem o documento assinado (RF-809). A etapa
    "emitido e aguardando digitalização" chega com a emissão do MOD-05."""

    codigo = "termo_a_emitir"
    prioridade = Prioridade.ALTA
    perfis = frozenset({R, A, E})

    def __init__(self, leitura: LeituraCadastro) -> None:
        self._leitura = leitura

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        repositorio = uow.repositorio(RepositorioOperacao)
        trocas = repositorio.trocas_sem_documento(ids)
        extras = repositorio.extras(ids, date(1900, 1, 1), date(9999, 12, 31))
        com_termo = {(p, c) for p, c, _ in repositorio.termos(ids)}
        meses: dict[tuple[int, str], date] = {}
        for e in extras:
            chave = (e.paciente_id, competencia(e.data))
            if chave not in com_termo:
                meses[chave] = min(meses.get(chave, e.data), e.data)
        vivos = set(self._leitura.identificacoes(uow, sorted({t.paciente_id for t in trocas} | {p for p, _ in meses})))
        itens = [
            self._item(
                _no_inicio(t.data_origem),
                f"Declaração de troca de turno a emitir e assinar ({t.data_origem:%d/%m} para {t.data_destino:%d/%m})",
                t.paciente_id, _ficha(t.paciente_id),
            )
            for t in trocas
            if t.paciente_id in vivos
        ]  # fmt: skip
        for (pid, comp), primeira in sorted(meses.items()):
            if pid in vivos:
                mes = f"{comp[5:]}/{comp[:4]}"
                itens.append(self._item(_no_inicio(primeira), f"Termo de diálise extra de {mes} a emitir e assinar",
                                        pid, _ficha(pid)))  # fmt: skip
        return itens


class FontePresencaSemRegistro(_Fonte):
    """Linha 7: presença fora da escala acrescentada pela recepção sem troca nem extra planejada; a enfermagem dá
    ciência (RF-921). A presença vale; a classificação continua derivada."""

    codigo = "presenca_sem_registro"
    prioridade = Prioridade.NORMAL
    perfis = frozenset({E})

    def __init__(self, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._leitura = leitura
        self._parametros = parametros

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        implantacao = dados.implantacao(self._parametros) or date(1900, 1, 1)
        presencas = uow.repositorio(RepositorioOperacao).presencas_fora_da_escala(
            ids, implantacao, _hoje(contexto), sem_planejamento=True, sem_ciencia=True
        )
        vivos = set(self._leitura.identificacoes(uow, sorted({p.paciente_id for p in presencas})))
        por_id = dados.escalas(uow)
        itens = []
        for p in presencas:
            if p.paciente_id in vivos:
                sessao = Sessao(p.data, por_id[p.escala_id])
                turno = sessao.escala.rotulo.lower()
                descricao = f"Presença em {p.data:%d/%m/%Y}, {turno}, sem troca nem extra registrada"
                itens.append(self._item(sessao.inicio.astimezone(UTC), descricao, p.paciente_id, _ficha(p.paciente_id)))
        return itens


class FonteExtraAlemDoLimite(_Fonte):
    """Linha 8: mais de quatro extras provisórias no mês corrente (RN-01). Sinaliza, nunca bloqueia; encerra no fim do
    mês ou quando a extra é compensada."""

    codigo = "extra_alem_do_limite"
    prioridade = Prioridade.NORMAL
    perfis = frozenset({R, A, E})

    def __init__(self, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._leitura = leitura
        self._parametros = parametros

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        comp = competencia(_hoje(contexto))
        primeiro, ultimo = limites_da_competencia(comp)
        fora = uow.repositorio(RepositorioOperacao).presencas_fora_da_escala(
            ids, primeiro, ultimo, sem_planejamento=False, sem_ciencia=False
        )
        candidatos = sorted(pid for pid, n in Counter(p.paciente_id for p in fora).items() if n > LIMITE_EXTRAS)
        if not candidatos:
            return []
        apurados = apurar(uow, self._leitura, dados.implantacao(self._parametros), comp, contexto.instante, candidatos)
        mes = f"{comp[5:]}/{comp[:4]}"
        itens = []
        for pid, apurado in apurados.items():
            extras = len(apurado.compensacao.extras)
            if extras > LIMITE_EXTRAS:
                descricao = f"{extras} sessões extras em {mes} (limite de {LIMITE_EXTRAS})"
                itens.append(self._item(_no_inicio(primeiro), descricao, pid, _ficha(pid)))
        return itens


def fontes(leitura: LeituraCadastro, parametros: LeitorParametros) -> tuple[FontePendencia, ...]:
    return (
        FonteSessaoNaoConfirmada(parametros),
        FonteTermoAEmitir(leitura),
        FonteSemAlocacao(leitura),
        FontePresencaSemRegistro(leitura, parametros),
        FonteExtraAlemDoLimite(leitura, parametros),
    )
