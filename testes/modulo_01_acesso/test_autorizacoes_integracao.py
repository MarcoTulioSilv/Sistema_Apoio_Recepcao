"""Autorizações (DDS §5.3, DEC-42, P-01) no MySQL: CT-AUD-06 e QAS-10, com um executor de teste."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoAutorizacoes
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.portas import Autorizacao
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.acesso import CriarUsuario
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao

ANULAR = "cadastro.paciente.anular"  # "Aut." para recepção e administração (§4.2)
AGORA = datetime(2026, 10, 8, 14, 0, tzinfo=UTC)


@dataclass
class ExecutorFalso:
    """Faz o papel do executor do MOD-02: audita a operação com o autor e o autorizador recebidos."""

    tipo: str = ANULAR
    versoes: dict[str, int] = field(default_factory=dict)
    chamadas: list[tuple[Any, ...]] = field(default_factory=list)
    falhar: bool = False

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        return f"Anular o cadastro {parametros['paciente_id']}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return self.versoes.get(entidade_id, 1)

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
    ) -> None:
        if self.falhar:
            raise RuntimeError("executor falhou")
        self.chamadas.append((autor.usuario_id, autor.perfil, autor.sessao_id, autorizacao))
        ServicoAuditoria().registrar(
            uow, autor, ANULAR, "paciente", str(parametros["paciente_id"]), {"anulado": (False, True)}, None,
            autorizacao.autorizador_id,
        )  # fmt: skip


@pytest.fixture
def pessoas(
    usuarios: dict[str, int], criar_usuario: CriarUsuario, trilha_zerada: Engine
) -> Iterator[dict[str, Contexto]]:
    """Recepção, administração (duas), enfermagem e visualizador; no fim, apaga as solicitações antes deles."""
    outros = {
        "admin2": criar_usuario("aut_admin2", perfil="administracao"),
        "enfermagem": criar_usuario("aut_enfermagem", perfil="enfermagem"),
        "visualizador": criar_usuario("aut_visualizador", perfil="visualizador"),
    }
    perfis = {"recepcao": Perfil.RECEPCAO, "admin": Perfil.ADMINISTRACAO, "admin2": Perfil.ADMINISTRACAO,
              "enfermagem": Perfil.ENFERMAGEM, "visualizador": Perfil.VISUALIZADOR}  # fmt: skip
    ids = {**usuarios, **outros}
    yield {chave: Contexto(ids[chave], perfil, None, "10.0.0.9", AGORA, "a" * 32) for chave, perfil in perfis.items()}
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM solicitacao_autorizacao"))


def montar(engine: Engine, executor: ExecutorFalso) -> ServicoAutorizacoes:
    return ServicoAutorizacoes(
        montar_executor(engine, montar_barramento(RelogioControlado(AGORA))), ServicoAuditoria(), {ANULAR: executor}
    )


def estado(engine: Engine, solicitacao_id: str) -> tuple[object, ...]:
    with engine.connect() as c:
        sql = "SELECT estado, decisor_id, versao_alvo FROM solicitacao_autorizacao WHERE id = UNHEX(:i)"
        return tuple(c.execute(text(sql), {"i": solicitacao_id}).one())


def auditoria_da_operacao(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as c:
        sql = "SELECT usuario_id, autorizador_id, sessao_id FROM auditoria WHERE operacao = :o"
        return [tuple(linha) for linha in c.execute(text(sql), {"o": ANULAR})]


@pytest.mark.requisito("RF-1008", "CT-AUD-06", "QAS-10", "DEC-42")
def test_recepcao_pede_administracao_aprova_e_a_trilha_guarda_as_duas_identidades(
    pessoas: dict[str, Contexto], engine_web: Engine
) -> None:
    executor = ExecutorFalso()
    servico = montar(engine_web, executor)
    recepcao, admin = pessoas["recepcao"], pessoas["admin"]
    sid = servico.solicitar(recepcao, ANULAR, "42", {"paciente_id": 42}, "Cadastro duplicado por engano")
    assert estado(engine_web, sid) == ("pendente", None, 1)
    assert [p.descricao for p in servico.pendentes(admin)] == ["Anular o cadastro 42"]
    assert executor.chamadas == []

    assert servico.aprovar(admin, sid) == "executada"
    assert estado(engine_web, sid)[:2] == ("executada", admin.usuario_id)
    assinatura = Autorizacao(sid, admin.usuario_id, "Cadastro duplicado por engano")  # a marca de mês alterado usa
    assert executor.chamadas == [(recepcao.usuario_id, Perfil.RECEPCAO, None, assinatura)]
    assert auditoria_da_operacao(engine_web) == [(recepcao.usuario_id, admin.usuario_id, None)]
    assert servico.pendentes(admin) == []


@pytest.mark.requisito("CT-AUD-06", "P-01", "RF-1008")
def test_pedido_da_administracao_nasce_executado(pessoas: dict[str, Contexto], engine_web: Engine) -> None:
    executor = ExecutorFalso()
    servico = montar(engine_web, executor)
    admin = pessoas["admin"]
    sid = servico.solicitar(admin, ANULAR, "43", {"paciente_id": 43}, "Paciente cadastrado em duplicidade")
    assert estado(engine_web, sid) == ("executada", admin.usuario_id, None)  # sem fila e sem conferir versão
    assert auditoria_da_operacao(engine_web) == [(admin.usuario_id, admin.usuario_id, None)]
    assert servico.pendentes(admin) == []


@pytest.mark.requisito("CT-AUD-06", "DDS-5.3")
def test_alvo_alterado_depois_do_pedido_invalida_sem_executar(pessoas: dict[str, Contexto], engine_web: Engine) -> None:
    executor = ExecutorFalso()
    servico = montar(engine_web, executor)
    sid = servico.solicitar(pessoas["recepcao"], ANULAR, "44", {"paciente_id": 44}, "Duplicado")
    executor.versoes["44"] = 2  # alguém alterou o cadastro enquanto o pedido esperava
    assert servico.aprovar(pessoas["admin"], sid) == "invalidada"
    assert executor.chamadas == [] and estado(engine_web, sid)[0] == "invalidada"
    with pytest.raises(RegraViolada) as erro:
        servico.aprovar(pessoas["admin"], sid)  # estado final
    assert erro.value.codigo == "autorizacao.ja_decidida"


@pytest.mark.requisito("DDS-5.3")
def test_recusa_exige_motivo_e_cancelamento_so_pelo_proprio(pessoas: dict[str, Contexto], engine_web: Engine) -> None:
    servico = montar(engine_web, ExecutorFalso())
    recusar = servico.solicitar(pessoas["recepcao"], ANULAR, "45", {"paciente_id": 45}, "Duplicado")
    with pytest.raises(RegraViolada):
        servico.recusar(pessoas["admin"], recusar, "   ")
    servico.recusar(pessoas["admin"], recusar, "Não é duplicidade: são homônimos")
    assert estado(engine_web, recusar)[0] == "recusada"

    cancelar = servico.solicitar(pessoas["recepcao"], ANULAR, "46", {"paciente_id": 46}, "Duplicado")
    with pytest.raises(AcessoNegado):
        servico.cancelar(pessoas["admin"], cancelar)  # não é dele
    servico.cancelar(pessoas["recepcao"], cancelar)
    assert estado(engine_web, cancelar)[0] == "cancelada"
    # mesmo instante (relógio fixo): a ordem entre as duas não é garantida
    assert sorted(s.estado for s in servico.minhas(pessoas["recepcao"])) == ["cancelada", "recusada"]


@pytest.mark.requisito("CT-ACE-01", "DEC-42")
def test_so_pede_quem_a_matriz_marca_com_aut(pessoas: dict[str, Contexto], engine_web: Engine) -> None:
    servico = montar(engine_web, ExecutorFalso())
    for quem in ("enfermagem", "visualizador"):  # não alcançam a anulação de cadastro
        with pytest.raises(AcessoNegado):
            servico.solicitar(pessoas[quem], ANULAR, "47", {"paciente_id": 47}, "Duplicado")
    with pytest.raises(AcessoNegado):  # a recepção cria cadastro direto: não há o que pedir
        servico.solicitar(pessoas["recepcao"], "cadastro.paciente.criar", "47", {}, "Pedido")
    with pytest.raises(RegraViolada):  # "Aut." para a recepção, mas sem executor registrado
        servico.solicitar(pessoas["recepcao"], "operacao.sessao.reabrir", "7", {}, "Sessão confirmada com erro")
    with pytest.raises(AcessoNegado):
        servico.aprovar(pessoas["recepcao"], "0" * 32)  # só a administração decide
    with pytest.raises(NaoEncontrado):
        servico.aprovar(pessoas["admin"], "0" * 32)


@pytest.mark.requisito("CT-AUD-06", "DD-03")
def test_falha_do_executor_desfaz_a_aprovacao(pessoas: dict[str, Contexto], engine_web: Engine) -> None:
    executor = ExecutorFalso()
    servico = montar(engine_web, executor)
    sid = servico.solicitar(pessoas["recepcao"], ANULAR, "48", {"paciente_id": 48}, "Duplicado")
    executor.falhar = True
    with pytest.raises(RuntimeError):
        servico.aprovar(pessoas["admin"], sid)
    assert estado(engine_web, sid)[0] == "pendente"  # tudo na mesma transação
    assert auditoria_da_operacao(engine_web) == []


@pytest.mark.requisito("CT-AUD-06", "DDS-5.3")
def test_duas_aprovacoes_simultaneas_executam_uma_vez(pessoas: dict[str, Contexto], engine_web: Engine) -> None:
    executor = ExecutorFalso()
    servico = montar(engine_web, executor)
    sid = servico.solicitar(pessoas["recepcao"], ANULAR, "49", {"paciente_id": 49}, "Duplicado")

    def aprovar(chave: str) -> str:
        try:
            return servico.aprovar(pessoas[chave], sid)
        except RegraViolada as erro:
            return erro.codigo

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = sorted(pool.map(aprovar, ["admin", "admin2"]))
    assert resultados == ["autorizacao.ja_decidida", "executada"]
    assert len(executor.chamadas) == 1
