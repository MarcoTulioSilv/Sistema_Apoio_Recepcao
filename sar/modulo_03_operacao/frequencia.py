"""Frequência do paciente (DDS §7.4, §7.5): balanço, pareamento e refazer (RF-916, RF-918) e a ciência da enfermagem
(RF-921)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from sar.modulo_01_acesso.contrato import AuditService, AutorizacaoService, PermissionGuard
from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.apuracao import Apurado, apurar, lista_da_sessao, mes_fechado
from sar.modulo_03_operacao.calendario import Sessao
from sar.modulo_03_operacao.contrato import (
    BalancoMes,
    ItemFrequencia,
    Origem,
    ParDoMes,
    PareamentoDoMes,
    PresencaACientificar,
)
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada, RequerAutorizacao
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
REFAZER = "operacao.pareamento.refazer"
CIENCIA = "operacao.presenca.dar_ciencia"
_COMPETENCIA = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def validar_competencia(comp: str) -> str:
    if not _COMPETENCIA.match(comp):
        raise RegraViolada("competencia.invalida")
    return comp


def _hoje(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO_CLINICA).date()


def _apurado(
    uow: UnidadeDeTrabalho,
    leitura: LeituraCadastro,
    parametros: LeitorParametros,
    contexto: Contexto,
    pid: int,
    comp: str,
) -> Apurado | None:
    if leitura.identificacao(uow, pid) is None:
        raise NaoEncontrado()
    return apurar(uow, leitura, dados.implantacao(parametros), comp, contexto.instante, [pid]).get(pid)


def _balanco(comp: str, apurado: Apurado | None, fechado: bool) -> BalancoMes:
    if apurado is None:  # sem período: nada previsto nem realizado
        return BalancoMes(comp, 0, 0, 0, 0, 0, 0, not fechado)
    b = apurado.compensacao.balanco(fechado)
    return BalancoMes(comp, b.previstas, b.realizadas, b.ausencias_nao_compensadas, b.reposicoes, b.extras,
                      b.a_realizar, b.provisorio)  # fmt: skip


def montar_pareamento(comp: str, apurado: Apurado | None, fechado: bool) -> PareamentoDoMes:
    """Os pares com a origem de cada um, as ausências livres e as extras, para a ficha e para o relatório."""
    if apurado is None:
        return PareamentoDoMes(_balanco(comp, None, fechado), (), (), (), 0, fechado)
    linhas, c = apurado.presencas, apurado.compensacao

    def item(s: Sessao) -> ItemFrequencia:
        return ItemFrequencia(s.data, s.escala, linhas[s].id if s in linhas else None)

    return PareamentoDoMes(
        _balanco(comp, apurado, fechado),
        tuple(ParDoMes(item(p.ausencia), item(p.presenca), p.origem) for p in c.pares),
        tuple(item(a) for a in c.ausencias_livres),
        tuple(item(e) for e in c.extras),
        len(c.ligacoes_ignoradas),
        fechado,
    )


def _texto(ligacoes: Sequence[tuple[int, int]]) -> str:
    return ";".join(f"{a}>{p}" for a, p in sorted(ligacoes))


def gravar_ligacoes(
    uow: UnidadeDeTrabalho,
    auditoria: AuditService,
    leitura: LeituraCadastro,
    parametros: LeitorParametros,
    contexto: Contexto,
    paciente_id: int,
    comp: str,
    ligacoes: Sequence[tuple[int, int]],
    autorizador_id: int | None = None,
) -> None:
    """Troca as ligações manuais do paciente no mês. Cada lado em no máximo uma ligação; a ausência precisa ser
    vaga prevista marcada ausente e a presença, fora da escala, ambas do paciente e do mês (§7.1, §7.4)."""
    if contexto.usuario_id is None:
        raise AcessoNegado()
    apurado = _apurado(uow, leitura, parametros, contexto, paciente_id, comp)
    linhas = apurado.presencas if apurado is not None else {}
    por_id = {p.id: s for s, p in linhas.items()}
    ausencias = set(apurado.compensacao.ausencias) if apurado else set()
    fora = set(apurado.compensacao.fora_da_escala) if apurado else set()
    lados_a = [a for a, _ in ligacoes]
    lados_p = [p for _, p in ligacoes]
    for i, (a, p) in enumerate(ligacoes):
        valida = por_id.get(a) in ausencias and por_id.get(p) in fora
        if not valida or lados_a.count(a) > 1 or lados_p.count(p) > 1:
            raise RegraViolada("ligacao.invalida", {"indice": i})
    repositorio = uow.repositorio(RepositorioOperacao)
    atuais = [li for li in repositorio.ligacoes(list(por_id)) if li.ausencia_id in por_id and li.presenca_id in por_id]
    antes, depois = _texto([(li.ausencia_id, li.presenca_id) for li in atuais]), _texto(ligacoes)
    if antes == depois:
        return  # nada muda (DD-10)
    repositorio.remover_ligacoes([li.id for li in atuais])
    for a, p in ligacoes:
        repositorio.criar_ligacao(a, p, contexto.usuario_id, contexto.instante)
    alteracoes = {"competencia": (None, comp), "ligacoes": (antes, depois)}
    auditoria.registrar(uow, contexto, REFAZER, "paciente", str(paciente_id), alteracoes, autorizador_id=autorizador_id)


class ServicoFrequencia:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        leitura: LeituraCadastro,
        parametros: LeitorParametros,
        autorizacoes: AutorizacaoService,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros
        self._autorizacoes = autorizacoes

    def balanco(self, contexto: Contexto, paciente_id: int, competencia: str) -> BalancoMes:
        GUARDA.exigir(contexto, "operacao.balanco.consultar")
        comp = validar_competencia(competencia)

        def operacao(uow: UnidadeDeTrabalho) -> BalancoMes:
            apurado = _apurado(uow, self._leitura, self._parametros, contexto, paciente_id, comp)
            return _balanco(comp, apurado, self._fechado(uow, comp, contexto))

        return self._executar(operacao)

    def pareamento_do_mes(self, contexto: Contexto, paciente_id: int, competencia: str) -> PareamentoDoMes:
        GUARDA.exigir(contexto, "operacao.balanco.consultar")
        comp = validar_competencia(competencia)

        def operacao(uow: UnidadeDeTrabalho) -> PareamentoDoMes:
            apurado = _apurado(uow, self._leitura, self._parametros, contexto, paciente_id, comp)
            return montar_pareamento(comp, apurado, self._fechado(uow, comp, contexto))

        return self._executar(operacao)

    def refazer(
        self, contexto: Contexto, paciente_id: int, competencia: str, ligacoes: Sequence[tuple[int, int]]
    ) -> None:
        if not (GUARDA.pode(contexto, REFAZER, "mês aberto") or GUARDA.solicitavel(contexto, REFAZER)):
            raise AcessoNegado()
        comp = validar_competencia(competencia)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            if self._fechado(uow, comp, contexto):
                raise RequerAutorizacao(REFAZER)  # mês fechado: só por autorização (DD-26)
            GUARDA.exigir(contexto, REFAZER, "mês aberto")
            gravar_ligacoes(
                uow, self._auditoria, self._leitura, self._parametros, contexto, paciente_id, comp, ligacoes
            )

        self._executar(operacao)

    def solicitar_refazer(
        self, contexto: Contexto, paciente_id: int, competencia: str, ligacoes: Sequence[tuple[int, int]], motivo: str
    ) -> str:
        if not GUARDA.solicitavel(contexto, REFAZER):
            raise AcessoNegado()
        comp = validar_competencia(competencia)
        parametros = {"paciente_id": paciente_id, "competencia": comp, "ligacoes": [[a, p] for a, p in ligacoes]}
        return self._autorizacoes.solicitar(contexto, REFAZER, f"{paciente_id}:{comp}", parametros, motivo)

    def presencas_sem_registro(self, contexto: Contexto) -> list[PresencaACientificar]:
        GUARDA.exigir(contexto, CIENCIA)

        def operacao(uow: UnidadeDeTrabalho) -> list[PresencaACientificar]:
            desde = dados.implantacao(self._parametros) or date(1900, 1, 1)
            presencas = uow.repositorio(RepositorioOperacao).presencas_fora_da_escala(
                None, desde, _hoje(contexto), sem_planejamento=True, sem_ciencia=True
            )
            nomes = self._leitura.identificacoes(uow, sorted({p.paciente_id for p in presencas}))
            por_id = dados.escalas(uow)
            itens = []
            for p in presencas:
                if p.paciente_id in nomes:
                    nome = nomes[p.paciente_id]
                    itens.append(
                        PresencaACientificar(
                            p.id, p.paciente_id, nome.nome, nome.prontuario, p.data, por_id[p.escala_id]
                        )
                    )
            return itens

        return self._executar(operacao)

    def dar_ciencia(self, contexto: Contexto, presenca_id: int) -> None:
        GUARDA.exigir(contexto, CIENCIA)
        if contexto.usuario_id is None:
            raise AcessoNegado()
        usuario = contexto.usuario_id

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioOperacao)
            presenca = repositorio.presenca_por_id(presenca_id)
            if presenca is None or self._leitura.identificacao(uow, presenca.paciente_id) is None:
                raise NaoEncontrado()
            sessao = Sessao(presenca.data, dados.escalas(uow)[presenca.escala_id])
            lista = lista_da_sessao(uow, self._leitura, sessao)
            item = next((i for i in lista.itens if i.paciente_id == presenca.paciente_id), None)
            if presenca.situacao != "presente" or item is None or item.origem is not Origem.ACRESCENTADO:
                raise RegraViolada("ciencia.desnecessaria")  # só a presença sem troca nem extra planejada (RF-921)
            if repositorio.ciencias([presenca_id]):
                raise RegraViolada("ciencia.ja_registrada")
            repositorio.criar_ciencia(presenca_id, contexto.instante, usuario)
            self._auditoria.registrar(uow, contexto, CIENCIA, "presenca", str(presenca_id), {"ciencia": (False, True)})

        self._executar(operacao)

    def _fechado(self, uow: UnidadeDeTrabalho, comp: str, contexto: Contexto) -> bool:
        return mes_fechado(uow, dados.implantacao(self._parametros), comp, _hoje(contexto))[0]


def ligacoes_dos_parametros(valor: object) -> list[tuple[int, int]]:
    """As ligações como vieram na solicitação (lista de pares de ids)."""
    if not isinstance(valor, list):
        raise RegraViolada("ligacao.invalida")
    return [(int(a), int(p)) for a, p in valor]
