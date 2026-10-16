"""Sessão de turno (DDS §7.3; DD-23, DD-24, DD-30, DD-32, DD-76): a tela do turno, as marcações, o acréscimo, a
confirmação e a sessão não realizada."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.apuracao import ListaDaSessao, apurar, lista_da_sessao
from sar.modulo_03_operacao.calendario import (
    CONFIRMAVEIS,
    DEVIDAS,
    MARCAVEIS,
    Antecedencias,
    Sessao,
    competencia,
    estado,
    existe,
    sessoes_entre,
)
from sar.modulo_03_operacao.contrato import (
    AusenciaDoMes,
    EstadoSessao,
    FrequenciaAoAcrescentar,
    Origem,
    PacienteNaSessao,
    PainelTurnos,
    ResumoSessao,
    TelaTurno,
)
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao, SessaoGravada, SituacaoPresenca
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, ConflitoDeVersao, NaoEncontrado, RegraViolada, RequerAutorizacao
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
MARCAR = "operacao.frequencia.marcar_ausencia"
ACRESCENTAR = "operacao.frequencia.acrescentar_paciente"
ALTERAR_CONFIRMADA = "operacao.presenca.alterar_confirmada"
TAMANHO_MOTIVO = 300


def _hoje(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO_CLINICA).date()


def _estado_gravado(sessao: Sessao, gravada: SessaoGravada | None, agora: datetime, ant: Antecedencias) -> EstadoSessao:
    confirmada = gravada is not None and gravada.confirmada_em is not None
    nao_realizada = gravada is not None and gravada.nao_realizada_motivo is not None
    return estado(sessao, agora, ant, confirmada=confirmada, nao_realizada=nao_realizada)


def _usuario(contexto: Contexto) -> int:
    if contexto.usuario_id is None:
        raise AcessoNegado()
    return contexto.usuario_id


class ServicoSessoes:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        leitura: LeituraCadastro,
        parametros: LeitorParametros,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros

    # ---------------------------------------------------------------- consulta
    def painel(self, contexto: Contexto) -> PainelTurnos:
        GUARDA.exigir(contexto, "operacao.sessao.ver")
        implantada = dados.implantacao(self._parametros)
        if implantada is None:
            return PainelTurnos(False, ())
        hoje = _hoje(contexto)
        antecedencias = self._antecedencias()

        def operacao(uow: UnidadeDeTrabalho) -> PainelTurnos:
            anteriores = self._nao_confirmadas(uow, contexto, implantada, hoje - timedelta(days=1), antecedencias)
            de_hoje = self._resumos(uow, contexto, implantada, hoje, hoje, antecedencias)
            agindo = [r for r in de_hoje if r.estado in MARCAVEIS]
            return PainelTurnos(True, tuple(anteriores + agindo))

        return self._executar(operacao)

    def devidas_nao_confirmadas(self, contexto: Contexto) -> list[ResumoSessao]:
        GUARDA.exigir(contexto, "operacao.sessao.ver")
        implantada = dados.implantacao(self._parametros)
        if implantada is None:
            return []
        antecedencias = self._antecedencias()
        return self._executar(
            lambda uow: self._nao_confirmadas(uow, contexto, implantada, _hoje(contexto), antecedencias)
        )

    def proximo_turno(self, contexto: Contexto) -> TelaTurno | None:
        GUARDA.exigir(contexto, "operacao.sessao.preparar")
        implantada = dados.implantacao(self._parametros)
        if implantada is None:
            return None
        hoje = _hoje(contexto)
        antecedencias = self._antecedencias()

        def operacao(uow: UnidadeDeTrabalho) -> TelaTurno | None:
            resumos = self._resumos(uow, contexto, implantada, hoje, hoje, antecedencias)
            proxima = next((r for r in resumos if r.estado is EstadoSessao.EM_PREPARACAO), None)
            if proxima is None:
                return None
            return self._tela(uow, contexto, Sessao(proxima.data, proxima.escala), antecedencias)

        return self._executar(operacao)

    def tela_do_turno(self, contexto: Contexto, data: date, escala_id: int) -> TelaTurno:
        GUARDA.exigir(contexto, "operacao.sessao.ver")
        antecedencias = self._antecedencias()
        return self._executar(lambda uow: self._tela(uow, contexto, self._sessao(uow, data, escala_id), antecedencias))

    def frequencia_ao_acrescentar(self, contexto: Contexto, paciente_id: int, data: date) -> FrequenciaAoAcrescentar:
        GUARDA.exigir(contexto, ACRESCENTAR)

        def operacao(uow: UnidadeDeTrabalho) -> FrequenciaAoAcrescentar:
            if self._leitura.identificacao(uow, paciente_id) is None:
                raise NaoEncontrado()
            return self._frequencia(uow, contexto, paciente_id, data)

        return self._executar(operacao)

    # ---------------------------------------------------------------- marcações (P-13, DD-24)
    def marcar_ausencia(self, contexto: Contexto, data: date, escala_id: int, paciente_id: int) -> int:
        GUARDA.exigir(contexto, MARCAR)
        return self._executar(lambda uow: self._mudar(uow, contexto, data, escala_id, paciente_id, presente=False))

    def desmarcar(self, contexto: Contexto, data: date, escala_id: int, paciente_id: int) -> int:
        GUARDA.exigir(contexto, MARCAR)
        return self._executar(lambda uow: self._mudar(uow, contexto, data, escala_id, paciente_id, presente=True))

    def _mudar(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, data: date, escala_id: int, paciente_id: int, presente: bool
    ) -> int:
        lista = self._lista_marcavel(uow, contexto, data, escala_id)
        item = next((i for i in lista.itens if i.paciente_id == paciente_id), None)
        if item is None:
            raise RegraViolada("paciente.fora_da_lista")
        repositorio = uow.repositorio(RepositorioOperacao)
        gravada = repositorio.garantir_sessao(data, escala_id)
        if item.presente == presente:
            return gravada.versao  # já está assim: nada é gravado nem auditado (DD-10)
        padrao = item.origem is not Origem.TROCA_SAINDO
        linha = next((p for p in lista.excecoes if p.paciente_id == paciente_id), None)
        if presente == padrao and item.origem is not Origem.ACRESCENTADO:
            if linha is not None:
                repositorio.remover_presenca(linha.id)  # de volta ao padrão: a exceção deixa de existir
        else:
            repositorio.gravar_presenca(gravada.id, paciente_id, "presente" if presente else "ausente")
        versao = repositorio.tocar_sessao(gravada.id)
        self._auditoria.registrar(
            uow, contexto, MARCAR, "sessao_turno", str(gravada.id),
            {"paciente_id": (None, paciente_id), "presente": (item.presente, presente)},
        )  # fmt: skip
        return versao

    # ---------------------------------------------------------------- acréscimo (DD-24, DD-25, RF-917)
    def acrescentar_paciente(
        self, contexto: Contexto, data: date, escala_id: int, paciente_id: int, ausencia_id: int | None = None
    ) -> FrequenciaAoAcrescentar:
        GUARDA.exigir(contexto, ACRESCENTAR)
        usuario = _usuario(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> FrequenciaAoAcrescentar:
            lista = self._lista_marcavel(uow, contexto, data, escala_id)
            if self._leitura.identificacao(uow, paciente_id) is None:
                raise NaoEncontrado()
            obito = self._leitura.data_obito(uow, paciente_id)
            if obito is not None and data > obito:
                raise RegraViolada("INV-01")
            if self._leitura.periodo_aberto_em(uow, paciente_id, data) is None:
                raise RegraViolada("INV-04")
            if any(i.paciente_id == paciente_id for i in lista.itens):
                raise RegraViolada("paciente.ja_na_lista")
            repositorio = uow.repositorio(RepositorioOperacao)
            gravada = repositorio.garantir_sessao(data, escala_id)
            presenca_id = repositorio.gravar_presenca(gravada.id, paciente_id, "presente")
            if ausencia_id is not None:
                self._ligar(uow, paciente_id, ausencia_id, presenca_id, data, usuario, contexto)
            repositorio.tocar_sessao(gravada.id)
            self._auditoria.registrar(
                uow, contexto, ACRESCENTAR, "sessao_turno", str(gravada.id),
                {"paciente_id": (None, paciente_id), "ausencia_ligada": (None, ausencia_id)},
            )  # fmt: skip
            return self._frequencia(uow, contexto, paciente_id, data)

        return self._executar(operacao)

    @staticmethod
    def _ligar(
        uow: UnidadeDeTrabalho,
        paciente_id: int,
        ausencia_id: int,
        presenca_id: int,
        data: date,
        usuario: int,
        contexto: Contexto,
    ) -> None:
        """Mesmo paciente e mesmo mês; cada lado em no máximo uma ligação (§7.1)."""
        repositorio = uow.repositorio(RepositorioOperacao)
        ausencia = repositorio.presenca_por_id(ausencia_id)
        valida = (
            ausencia is not None
            and ausencia.paciente_id == paciente_id
            and ausencia.situacao == "ausente"
            and competencia(ausencia.data) == competencia(data)
            and not repositorio.ligacoes([ausencia_id])
        )
        if not valida:
            raise RegraViolada("ligacao.invalida")
        repositorio.criar_ligacao(ausencia_id, presenca_id, usuario, contexto.instante)

    def retirar_acrescentado(self, contexto: Contexto, data: date, escala_id: int, paciente_id: int) -> int:
        GUARDA.exigir(contexto, ACRESCENTAR)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            lista = self._lista_marcavel(uow, contexto, data, escala_id)
            item = next((i for i in lista.itens if i.paciente_id == paciente_id), None)
            linha = next((p for p in lista.excecoes if p.paciente_id == paciente_id), None)
            if item is None or item.origem is not Origem.ACRESCENTADO or linha is None:
                raise RegraViolada("paciente.nao_acrescentado")
            repositorio = uow.repositorio(RepositorioOperacao)
            repositorio.remover_presenca(linha.id)
            versao = repositorio.tocar_sessao(linha.sessao_id)
            self._auditoria.registrar(
                uow, contexto, ACRESCENTAR, "sessao_turno", str(linha.sessao_id), {"paciente_id": (paciente_id, None)}
            )
            return versao

        return self._executar(operacao)

    # ---------------------------------------------------------------- confirmação (DD-24, DD-32, DD-17)
    def confirmar(self, contexto: Contexto, data: date, escala_id: int, versao: int) -> None:
        GUARDA.exigir(contexto, "operacao.sessao.confirmar")
        usuario = _usuario(contexto)
        antecedencias = self._antecedencias()

        def operacao(uow: UnidadeDeTrabalho) -> None:
            sessao = self._sessao(uow, data, escala_id)
            lista = lista_da_sessao(uow, self._leitura, sessao, travar=True)
            gravada = lista.gravada
            situacao = _estado_gravado(sessao, gravada, contexto.instante, antecedencias)
            if (gravada.versao if gravada is not None else 0) != versao:
                raise ConflitoDeVersao(None, None)  # outra estação marcou ou confirmou depois da leitura
            if situacao is EstadoSessao.CONFIRMADA:
                raise RegraViolada("sessao.confirmada")
            if situacao is EstadoSessao.NAO_REALIZADA:
                raise RegraViolada("sessao.nao_realizada")
            if situacao not in CONFIRMAVEIS:
                raise RegraViolada("sessao.confirmacao_nao_liberada")
            repositorio = uow.repositorio(RepositorioOperacao)
            if gravada is None:
                sessao_id, atual = repositorio.criar_sessao(data, escala_id), 1
            else:
                sessao_id, atual = gravada.id, gravada.versao
            na_lista = {i.paciente_id for i in lista.itens}
            gravadas = {p.paciente_id: p for p in lista.excecoes}
            for p in lista.excecoes:
                if p.paciente_id not in na_lista:  # perdeu o período depois da marcação (INV-04)
                    repositorio.remover_presenca(p.id)
            for item in lista.itens:
                situacao_item: SituacaoPresenca = "presente" if item.presente else "ausente"
                existente = gravadas.get(item.paciente_id)
                if existente is None or existente.situacao != situacao_item:
                    repositorio.gravar_presenca(sessao_id, item.paciente_id, situacao_item)
            if not repositorio.confirmar_sessao(sessao_id, atual, contexto.instante, usuario, None):
                raise ConflitoDeVersao(None, None)
            presentes = sum(i.presente for i in lista.itens)
            self._auditoria.registrar(
                uow, contexto, "operacao.sessao.confirmar", "sessao_turno", str(sessao_id),
                {"presentes": (None, presentes), "ausentes": (None, len(lista.itens) - presentes)},
            )  # fmt: skip

        self._com_conflito(operacao)

    def registrar_nao_realizada(self, contexto: Contexto, data: date, escala_id: int, motivo: str) -> None:
        GUARDA.exigir(contexto, "operacao.sessao.registrar_nao_realizada")
        usuario = _usuario(contexto)
        limpo = " ".join((motivo or "").split())
        if not limpo:
            raise RegraViolada("motivo.obrigatorio")
        if len(limpo) > TAMANHO_MOTIVO:
            raise RegraViolada("motivo.longo")
        antecedencias = self._antecedencias()

        def operacao(uow: UnidadeDeTrabalho) -> None:
            sessao = self._sessao(uow, data, escala_id)
            repositorio = uow.repositorio(RepositorioOperacao)
            gravada = repositorio.sessao(data, escala_id, travar=True)
            situacao = _estado_gravado(sessao, gravada, contexto.instante, antecedencias)
            if situacao in (EstadoSessao.CONFIRMADA, EstadoSessao.NAO_REALIZADA):
                raise RegraViolada("sessao.confirmada")
            if situacao not in DEVIDAS:
                raise RegraViolada("sessao.futura")
            if gravada is None:
                sessao_id, atual = repositorio.criar_sessao(data, escala_id), 1
            else:
                sessao_id, atual = gravada.id, gravada.versao
                for p in repositorio.presencas_da_sessao(sessao_id):  # nenhuma presença fica (P-12)
                    repositorio.remover_presenca(p.id)
            if not repositorio.confirmar_sessao(sessao_id, atual, contexto.instante, usuario, limpo):
                raise ConflitoDeVersao(None, None)
            self._auditoria.registrar(
                uow, contexto, "operacao.sessao.registrar_nao_realizada", "sessao_turno", str(sessao_id),
                {"nao_realizada": (False, True)}, limpo,
            )  # fmt: skip

        self._com_conflito(operacao)

    # ---------------------------------------------------------------- apoio
    def _antecedencias(self) -> Antecedencias:
        preparacao = self._parametros.valor("preparacao_turno_antecedencia")
        confirmacao = self._parametros.valor("confirmacao_turno_antecedencia")
        if not isinstance(preparacao, int) or not isinstance(confirmacao, int):
            raise RuntimeError("antecedências do turno fora do tipo declarado")
        return Antecedencias.em_minutos(preparacao, confirmacao)

    def _sessao(self, uow: UnidadeDeTrabalho, data: date, escala_id: int) -> Sessao:
        implantada = dados.implantacao(self._parametros)
        if implantada is None:
            raise RegraViolada("implantacao.indefinida")  # DD-91
        escala = dados.escalas(uow).get(escala_id)
        if escala is None or not existe(data, escala, implantada):
            raise RegraViolada("sessao.inexistente")
        return Sessao(data, escala)

    def _lista_marcavel(self, uow: UnidadeDeTrabalho, contexto: Contexto, data: date, escala_id: int) -> ListaDaSessao:
        sessao = self._sessao(uow, data, escala_id)
        lista = lista_da_sessao(uow, self._leitura, sessao, travar=True)
        situacao = _estado_gravado(sessao, lista.gravada, contexto.instante, self._antecedencias())
        if situacao is EstadoSessao.CONFIRMADA:
            raise RequerAutorizacao(ALTERAR_CONFIRMADA)
        if situacao is EstadoSessao.NAO_REALIZADA:
            raise RegraViolada("sessao.nao_realizada")
        if situacao not in MARCAVEIS:
            raise RegraViolada("sessao.fora_da_marcacao")
        return lista

    def _resumos(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        implantada: date,
        inicio: date,
        fim: date,
        antecedencias: Antecedencias,
    ) -> list[ResumoSessao]:
        if fim < inicio:
            return []
        gravadas = {(s.data, s.escala_id): s for s in uow.repositorio(RepositorioOperacao).sessoes(inicio, fim)}
        return [
            ResumoSessao(s.data, s.escala, _estado_gravado(s, gravadas.get((s.data, s.escala.id)), contexto.instante,
                                                             antecedencias))
            for s in sessoes_entre(dados.escalas(uow).values(), inicio, fim, implantada)
        ]  # fmt: skip

    def _nao_confirmadas(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, implantada: date, ate: date, antecedencias: Antecedencias
    ) -> list[ResumoSessao]:
        return [
            r for r in self._resumos(uow, contexto, implantada, implantada, ate, antecedencias) if r.estado in DEVIDAS
        ]

    def _tela(self, uow: UnidadeDeTrabalho, contexto: Contexto, sessao: Sessao, ant: Antecedencias) -> TelaTurno:
        lista = lista_da_sessao(uow, self._leitura, sessao)
        ids = [i.paciente_id for i in lista.itens]
        nomes = self._leitura.identificacoes(uow, ids)
        apurados = apurar(uow, self._leitura, dados.implantacao(self._parametros), sessao.competencia,
                          contexto.instante, ids)  # fmt: skip
        pacientes = sorted(
            (
                PacienteNaSessao(i.paciente_id, nomes[i.paciente_id].nome, nomes[i.paciente_id].prontuario, i.origem,
                                 i.presente, i.marcado, len(apurados[i.paciente_id].compensacao.extras))
                for i in lista.itens
                if i.paciente_id in nomes
            ),
            key=lambda p: (p.nome, p.paciente_id),
        )  # fmt: skip
        gravada = lista.gravada
        return TelaTurno(
            sessao.data, sessao.escala, _estado_gravado(sessao, gravada, contexto.instante, ant),
            gravada.versao if gravada is not None else 0, tuple(pacientes),
            gravada.nao_realizada_motivo if gravada is not None else None,
        )  # fmt: skip

    def _frequencia(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int, data: date
    ) -> FrequenciaAoAcrescentar:
        implantada = dados.implantacao(self._parametros)
        apurado = apurar(uow, self._leitura, implantada, competencia(data), contexto.instante, [paciente_id])
        if paciente_id not in apurado:
            return FrequenciaAoAcrescentar((), 0)
        compensacao = apurado[paciente_id].compensacao
        livres = set(compensacao.ausencias_livres)
        linhas = apurado[paciente_id].presencas
        ausencias = tuple(
            AusenciaDoMes(linhas[a].id if a in linhas else None, a.data, a.escala, a in livres)
            for a in compensacao.ausencias
        )
        return FrequenciaAoAcrescentar(ausencias, len(compensacao.extras))

    def _com_conflito(self, operacao: Callable[[UnidadeDeTrabalho], None]) -> None:
        """A segunda estação que cria a mesma sessão ao mesmo tempo esbarra no único (data, escala): é conflito."""
        try:
            self._executar(operacao)
        except ConflitoDeVersao:
            raise
        except Exception as erro:
            if campos_do_erro(erro).get("restricao") == "uq_sessao_turno__data_escala":
                raise ConflitoDeVersao(None, None) from None
            raise
