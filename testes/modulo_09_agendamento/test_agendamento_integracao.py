"""Jobs com o banco, pelo usuário do worker (DD-58): trava, registro, cursor, execução manual, registro do backup e as
pendências 17 e 19 (DDS §11.1, §13; DD-61, DD-62, DD-64, DD-111, DD-112)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from sar.cli import main
from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_08_dados.repositorios.agendamento import TravaMySQL
from sar.modulo_09_agendamento.catalogo import CATALOGO, POR_NOME
from sar.modulo_09_agendamento.contrato import Job, JobEmAndamento, Resultado, ResultadoJob
from sar.modulo_09_agendamento.pendencias import FonteDiscoAcimaDoLimite, FonteJobAtrasado
from sar.modulo_09_agendamento.servicos import TRAVA_PESADAS, ServicoAgendamento
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado
from sar.nucleo.portas import ItemPendencia
from testes.apoio.acesso import ParametrosPadrao
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)  # terça, 10h em Jataí
IMPLANTACAO = date(2026, 11, 2)


def sistema(origem: str = "job.teste") -> Contexto:
    return Contexto.sistema(origem, AGORA)


TI = Contexto(1, Perfil.TI, 1, "10.0.0.9", AGORA, "e" * 32)


@dataclass
class RotinaFalsa:
    """Registra as chamadas; pode segurar a execução até o teste liberar, devolver um cursor ou falhar."""

    resultados: list[ResultadoJob] = field(default_factory=lambda: [ResultadoJob(3)])
    erro: Exception | None = None
    segurar: threading.Event | None = None
    comecou: threading.Event = field(default_factory=threading.Event)
    chamadas: list[tuple[str | None, float | None]] = field(default_factory=list)

    def __call__(self, contexto: Contexto, cursor: str | None, segundos: float | None) -> ResultadoJob:
        self.chamadas.append((cursor, segundos))
        self.comecou.set()
        if self.segurar is not None:
            self.segurar.wait(10)
        if self.erro is not None:
            raise self.erro
        return self.resultados[min(len(self.chamadas), len(self.resultados)) - 1]


@dataclass
class Cenario:
    engine: Engine
    relogio: RelogioControlado
    parametros: ParametrosPadrao

    def servico(self, *jobs: Job) -> ServicoAgendamento:
        executar = montar_executor(self.engine, montar_barramento(self.relogio))
        return ServicoAgendamento(executar, ServicoAuditoria(executar), self.parametros, TravaMySQL(self.engine),
                                  jobs or CATALOGO, self.relogio)  # fmt: skip

    def itens(self, fonte: FonteJobAtrasado | FonteDiscoAcimaDoLimite, contexto: Contexto) -> list[ItemPendencia]:
        executar = montar_executor(self.engine, montar_barramento(self.relogio))
        return executar(lambda uow: fonte.listar(uow, contexto))

    def linhas(self, sql: str) -> list[tuple[object, ...]]:
        with self.engine.connect() as c:
            return [tuple(linha) for linha in c.execute(text(sql))]


@pytest.fixture
def cenario(engine_worker: Engine, trilha_zerada: Engine) -> Iterator[Cenario]:
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM job_execucao"))
    yield Cenario(engine_worker, RelogioControlado(AGORA), ParametrosPadrao(data_implantacao=IMPLANTACAO))  # type: ignore[arg-type]
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM job_execucao"))


def job(nome: str, rotina: RotinaFalsa, **trocas: object) -> Job:
    return replace(POR_NOME[nome], rotina=rotina, **trocas)  # type: ignore[arg-type]


# ------------------------------------------------------------------ CT-JOB-02: trava
@pytest.mark.requisito("DD-61", "R-38", "CT-JOB-02")
def test_duas_execucoes_do_mesmo_job_uma_e_recusada(cenario: Cenario) -> None:
    segurar = threading.Event()
    rotina = RotinaFalsa(segurar=segurar)
    disco = job("ocupacao_disco", rotina)
    primeira, segunda = cenario.servico(disco), cenario.servico(disco)  # dois workers
    resultado: list[object] = []
    linha = threading.Thread(target=lambda: resultado.append(primeira.rodar(disco, sistema(), None)))
    linha.start()
    assert rotina.comecou.wait(10)
    assert segunda.rodar(disco, sistema(), None) is None  # trava ocupada
    with pytest.raises(JobEmAndamento):
        segunda.executar(sistema("cli.job"), "ocupacao_disco")
    segurar.set()
    linha.join(10)
    assert len(rotina.chamadas) == 1
    assert cenario.linhas("SELECT job, resultado FROM job_execucao") == [("ocupacao_disco", "sucesso")]


@pytest.mark.requisito("DD-64", "CT-JOB-02")
def test_pesada_espera_a_serie_e_falha_se_passar_do_limite(cenario: Cenario) -> None:
    rotina = RotinaFalsa()
    orfaos = job("orfaos_repositorio", rotina)
    with TravaMySQL(cenario.engine).obter(TRAVA_PESADAS, 0) as obtida:  # a rotina anterior ainda roda
        assert obtida
        feita = cenario.servico(orfaos).rodar(orfaos, sistema(), 1)
    assert feita is not None and feita.resultado is Resultado.FALHA and feita.resumo_erro == "JobEmAndamento"
    assert rotina.chamadas == []
    depois = cenario.servico(orfaos).rodar(orfaos, sistema(), 1)  # liberada: roda
    assert depois is not None and depois.resultado is Resultado.SUCESSO


# ------------------------------------------------------------------ CT-JOB-03: registro sem dado pessoal
@pytest.mark.requisito("DD-61", "RNF-624", "CT-JOB-03")
def test_falha_grava_so_o_nome_do_erro(cenario: Cenario) -> None:
    rotina = RotinaFalsa(erro=ValueError("Maria da Silva Fictícia, CPF 123.456.789-09"))
    feita = cenario.servico().rodar(job("descarte_rascunhos", rotina), sistema(), None)
    assert feita is not None and feita.resultado is Resultado.FALHA and feita.resumo_erro == "ValueError"
    ((resumo, fim),) = cenario.linhas("SELECT resumo_erro, fim FROM job_execucao")
    assert resumo == "ValueError" and fim is not None


@pytest.mark.requisito("DD-61", "CT-JOB-03")
def test_sem_trabalho_conta_como_execucao_bem_sucedida(cenario: Cenario) -> None:
    servico = cenario.servico()
    feita = servico.rodar(job("descarte_rascunhos", RotinaFalsa([ResultadoJob(0, sem_trabalho=True)])), sistema(), None)
    assert feita is not None and feita.resultado is Resultado.SEM_TRABALHO and feita.itens == 0
    assert "descarte_rascunhos" in servico.ultimos_sucessos()


# ------------------------------------------------------------------ CT-JOB-05: cursor e limite
@pytest.mark.requisito("DD-64", "SEG-22", "CT-JOB-05")
def test_rotina_com_cursor_continua_de_onde_parou(cenario: Cenario) -> None:
    rotina = RotinaFalsa([ResultadoJob(50, cursor="ab" * 16), ResultadoJob(20)])
    rescan = job("rescan_acervo", rotina)
    servico = cenario.servico(rescan)
    primeira = servico.rodar(rescan, sistema(), None)
    assert primeira is not None and primeira.parcial
    assert rotina.chamadas[0][0] is None and rotina.chamadas[0][1] is not None  # agendada: tem limite (04:30)
    assert "rescan_acervo" not in servico.ultimos_sucessos()  # passada incompleta não é sucesso para a pendência 17
    segunda = servico.rodar(rescan, sistema(), None)
    assert rotina.chamadas[1][0] == "ab" * 16
    assert segunda is not None and not segunda.parcial
    assert "rescan_acervo" in servico.ultimos_sucessos()
    servico.rodar(rescan, sistema(), None)
    assert rotina.chamadas[2][0] is None  # passada completa: a próxima recomeça


# ------------------------------------------------------------------ CT-JOB-07: execução manual (DD-112)
@pytest.mark.requisito("DD-112", "CT-JOB-07")
def test_execucao_manual_so_pela_linha_de_comando_e_auditada(cenario: Cenario) -> None:
    rotina = RotinaFalsa()
    servico = cenario.servico(job("ocupacao_disco", rotina), job("expurgo_trilha", RotinaFalsa()))
    with pytest.raises(AcessoNegado):
        servico.executar(TI, "ocupacao_disco")  # pela tela, o TI só consulta
    with pytest.raises(AcessoNegado):
        servico.executar(sistema("cli.job"), "expurgo_trilha")  # sem execução manual na §13.1
    feita = servico.executar(sistema("cli.job"), "ocupacao_disco")
    assert feita.resultado is Resultado.SUCESSO and rotina.chamadas == [(None, None)]
    auditoria = cenario.linhas("SELECT operacao, entidade, entidade_id FROM auditoria")
    assert auditoria == [("agendamento.job.executar_agora", "job_execucao", str(feita.id))]


# ------------------------------------------------------------------ CT-JOB-04: pendência 17 e o backup (DD-62)
@pytest.mark.requisito("R-38", "DD-61", "DD-62", "CT-JOB-04", "CT-PEN-05")
def test_backup_atrasado_abre_e_registro_encerra_a_pendencia(cenario: Cenario) -> None:
    servico = cenario.servico()
    fonte = FonteJobAtrasado(CATALOGO, cenario.parametros)  # type: ignore[arg-type]
    atrasados = {i.identificador_interno for i in cenario.itens(fonte, TI)}
    assert "backup" in atrasados  # nunca rodou, e a implantação foi há mais de 2 dias
    assert all(i.paciente_id is None for i in cenario.itens(fonte, TI))
    assert cenario.itens(fonte, replace(TI, perfil=Perfil.ADMINISTRACAO)) == []

    inicio = AGORA - timedelta(hours=8)
    servico.registrar_externo(sistema("cli.job.registrar"), "backup", Resultado.SUCESSO, inicio,
                              inicio + timedelta(minutes=12))  # fmt: skip
    assert "backup" not in {i.identificador_interno for i in cenario.itens(fonte, TI)}
    auditoria = cenario.linhas("SELECT operacao FROM auditoria")
    assert auditoria == [("agendamento.backup.registrar",)]

    tres_dias = replace(TI, instante=AGORA + timedelta(days=3))
    assert "backup" in {i.identificador_interno for i in cenario.itens(fonte, tres_dias)}
    with pytest.raises(LookupError):
        servico.registrar_externo(sistema(), "ocupacao_disco", Resultado.SUCESSO, inicio, AGORA)


@pytest.mark.requisito("R-38", "CT-JOB-04")
def test_falha_registrada_nao_encerra_a_pendencia(cenario: Cenario) -> None:
    cenario.servico().registrar_externo(sistema(), "backup", Resultado.FALHA, AGORA - timedelta(hours=1), AGORA)
    fonte = FonteJobAtrasado(CATALOGO, cenario.parametros)  # type: ignore[arg-type]
    assert "backup" in {i.identificador_interno for i in cenario.itens(fonte, TI)}


@pytest.mark.requisito("R-38", "DD-91")
def test_antes_da_implantacao_nada_esta_atrasado(cenario: Cenario) -> None:
    fonte = FonteJobAtrasado(CATALOGO, ParametrosPadrao())  # type: ignore[arg-type]
    assert cenario.itens(fonte, TI) == []


# ------------------------------------------------------------------ CT-JOB-06: pendência 19 (DD-111)
@pytest.mark.requisito("RNF-621", "DD-111", "CT-JOB-06", "CT-PEN-05")
def test_alarme_de_disco_abre_e_fecha_pela_ultima_medicao(cenario: Cenario) -> None:
    fonte = FonteDiscoAcimaDoLimite(cenario.parametros)  # type: ignore[arg-type]
    servico = cenario.servico()
    servico.rodar(job("ocupacao_disco", RotinaFalsa([ResultadoJob(86)])), sistema(), None)
    (item,) = cenario.itens(fonte, TI)
    assert "86%" in item.descricao and item.identificador_interno == "ocupacao_disco"
    servico.rodar(job("ocupacao_disco", RotinaFalsa([ResultadoJob(84)])), sistema(), None)
    assert cenario.itens(fonte, TI) == []
    alto = FonteDiscoAcimaDoLimite(ParametrosPadrao(disco_alarme_ocupacao=80))  # type: ignore[arg-type]
    assert len(cenario.itens(alto, TI)) == 1  # o TI baixou o alarme


# ------------------------------------------------------------------ consulta e linha de comando
@pytest.mark.requisito("DD-112", "R-38")
def test_situacao_para_o_ti(cenario: Cenario) -> None:
    servico = cenario.servico()
    servico.rodar(job("ocupacao_disco", RotinaFalsa()), sistema(), None)
    situacao = {s.nome: s for s in servico.situacao(TI)}
    assert set(situacao) == set(POR_NOME)
    assert not situacao["ocupacao_disco"].atrasado and situacao["ocupacao_disco"].ultima is not None
    assert situacao["backup"].atrasado
    assert not situacao["consumidor_fila"].atrasado  # laço, não job: só atrasa com fila parada (DD-63)
    with pytest.raises(AcessoNegado):
        servico.situacao(replace(TI, perfil=Perfil.ADMINISTRACAO))
    assert [e.job for e in servico.execucoes(TI)] == ["ocupacao_disco"]


@pytest.mark.requisito("DD-62", "DD-112")
def test_linha_de_comando_registra_o_backup(cenario: Cenario, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = main(["job", "registrar", "backup", "--resultado", "sucesso", "--inicio", "2026-11-10T02:20:00-03:00",
                   "--fim", "2026-11-10T02:41:10-03:00"])  # fmt: skip
    assert codigo == 0 and "backup: sucesso" in capsys.readouterr().out
    ((nome, resultado, inicio),) = cenario.linhas("SELECT job, resultado, inicio FROM job_execucao")
    assert (nome, resultado) == ("backup", "sucesso")
    assert inicio == datetime(2026, 11, 10, 5, 20, tzinfo=UTC).replace(tzinfo=None)  # gravado em UTC (§3.7)
    assert main(["job", "listar"]) in (0, 1)
    assert "backup" in capsys.readouterr().out
