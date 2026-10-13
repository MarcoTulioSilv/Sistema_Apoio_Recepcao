"""Telas de autorizações, trilha e integridade, com o banco de testes (§5.3, RNF-625, RF-1011, DD-86)."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text

import sar.composicao
from sar.composicao import compor_auditoria, montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoAutorizacoes
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.apoio.acesso import CriarUsuario
from testes.apoio.web import get, logado, montar, post

pytestmark = pytest.mark.integracao

ANULAR = "cadastro.paciente.anular"


class ExecutorFalso:
    tipo = ANULAR

    def descrever(self, uow: UnidadeDeTrabalho, parametros: Mapping[str, Any]) -> str:
        return f"Anular o cadastro {parametros['paciente_id']}"

    def versao_atual(self, uow: UnidadeDeTrabalho, entidade_id: str) -> int | None:
        return 1

    def executar(
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizador_id: int, parametros: Mapping[str, Any]
    ) -> None:
        pass


@pytest.fixture
def limpar(trilha_zerada: Engine) -> Iterator[None]:
    yield
    with trilha_zerada.begin() as c:
        c.execute(text("DELETE FROM solicitacao_autorizacao"))


def gravar(engine: Engine, usuario_id: int, entidade: str, quantidade: int = 1) -> None:
    executar = montar_executor(engine, montar_barramento(RelogioSistema()))
    contexto = Contexto(usuario_id, Perfil.RECEPCAO, None, "10.0.0.5", datetime.now(UTC), "c" * 32)
    for _ in range(quantidade):
        executar(lambda uow: ServicoAuditoria().registrar(uow, contexto, "teste.web", entidade, "7", {"x": (1, 2)}))


@pytest.mark.requisito("RNF-625", "RF-1006")
def test_trilha_completa_para_administracao_e_pseudonimizada_para_o_ti(
    criar_usuario: CriarUsuario, engine_web: Engine, limpar: None
) -> None:
    criar_usuario("webt_admin", perfil="administracao")
    criar_usuario("webt_ti", perfil="ti")
    recepcao = criar_usuario("webt_recepcao")
    gravar(engine_web, recepcao, "paciente")
    app = montar(engine_web)

    admin = get(logado(app, "webt_admin"), "/trilha?operacao=teste.").get_data(as_text=True)
    assert "teste.web" in admin and "{&#34;x&#34;:[1,2]}" in admin and "Detalhe oculto" not in admin
    ti = get(logado(app, "webt_ti"), "/trilha?operacao=teste.").get_data(as_text=True)
    assert 'data-sobre="pseudonimizado"' in ti and "[1,2]" not in ti

    recepcionista = logado(app, "webt_recepcao")
    assert "/trilha" not in get(recepcionista, "/").get_data(as_text=True)
    assert get(recepcionista, "/trilha").status_code == 403
    assert "formato do calendário" in get(logado(app, "webt_admin"), "/trilha?de=ontem").get_data(as_text=True)


@pytest.mark.requisito("RF-1011", "DEC-43", "DD-86")
def test_aviso_de_integridade_e_conferencia_do_codigo(
    criar_usuario: CriarUsuario, engine_web: Engine, engine_worker: Engine, trilha_zerada: Engine, limpar: None
) -> None:
    criar_usuario("webt_adm2", perfil="administracao")
    criar_usuario("webt_ti2", perfil="ti")
    uid = criar_usuario("webt_r2")
    gravar(engine_web, uid, "usuario", 3)
    sistema = Contexto.sistema("job", datetime.now(UTC))
    auditoria = compor_auditoria(engine_worker)
    auditoria.verificar_cadeia(sistema)  # íntegra: registra a âncora até o 3
    codigo = montar_executor(engine_web, montar_barramento(RelogioSistema()))(auditoria.codigo_vigente)
    assert codigo is not None
    app = montar(engine_web)
    admin = logado(app, "webt_adm2")

    sem_aviso = get(admin, "/integridade").get_data(as_text=True)
    assert "Nenhum aviso aberto" in sem_aviso
    confere = post(admin, "/integridade/conferir", {"registro": str(codigo.registro_id), "codigo": codigo.codigo})
    assert "O código confere" in confere.get_data(as_text=True)

    with trilha_zerada.begin() as c:
        c.execute(text("UPDATE auditoria SET motivo = 'adulterado' WHERE id = 2"))
    auditoria.verificar_cadeia(sistema)
    nao_confere = post(admin, "/integridade/conferir", {"registro": "2", "codigo": "0000-0000-0000-0000"})
    assert "NÃO confere" in nao_confere.get_data(as_text=True)

    simples = get(admin, "/integridade").get_data(as_text=True)
    assert "encontrou divergência" in simples and "Primeiro registro divergente" not in simples
    diagnostico = get(logado(app, "webt_ti2"), "/integridade").get_data(as_text=True)
    assert "Primeiro registro divergente: nº 2" in diagnostico and "Encerrar o aviso" not in diagnostico

    aviso = re.search(r'data-aviso="(\d+)"', simples)
    assert aviso is not None
    vazio = post(admin, f"/integridade/avisos/{aviso.group(1)}/encerrar", {"explicacao": " "})
    assert "Informe a explicação" in vazio.get_data(as_text=True)
    resposta = post(admin, f"/integridade/avisos/{aviso.group(1)}/encerrar", {"explicacao": "Teste de adulteração"})
    assert resposta.status_code == 302
    assert "Nenhum aviso aberto" in get(admin, "/integridade").get_data(as_text=True)


@pytest.mark.requisito("RF-1008", "CT-AUD-06")
def test_administracao_aprova_pela_fila(
    criar_usuario: CriarUsuario, engine_web: Engine, monkeypatch: pytest.MonkeyPatch, limpar: None
) -> None:
    monkeypatch.setitem(sar.composicao.EXECUTORES_AUTORIZAVEIS, ANULAR, ExecutorFalso())
    criar_usuario("webt_adm3", perfil="administracao")
    recepcao = criar_usuario("webt_r3")
    pedidos = ServicoAutorizacoes(
        montar_executor(engine_web, montar_barramento(RelogioSistema())), ServicoAuditoria(), {ANULAR: ExecutorFalso()}
    )
    contexto = Contexto(recepcao, Perfil.RECEPCAO, None, "10.0.0.5", datetime.now(UTC), "d" * 32)
    pedidos.solicitar(contexto, ANULAR, "42", {"paciente_id": 42}, "Cadastro duplicado")
    app = montar(engine_web)

    admin = logado(app, "webt_adm3")
    fila = get(admin, "/autorizacoes").get_data(as_text=True)
    assert "Anular o cadastro 42" in fila and "Cadastro duplicado" in fila
    solicitacao = re.search(r'data-solicitacao="([0-9a-f]{32})"', fila)
    assert solicitacao is not None
    sem_motivo = post(admin, f"/autorizacoes/{solicitacao.group(1)}/recusar", {"motivo": ""})
    assert "Informe o motivo" in sem_motivo.get_data(as_text=True)
    aprovada = post(admin, f"/autorizacoes/{solicitacao.group(1)}/aprovar", {"motivo": ""})
    assert "resultado=executada" in aprovada.headers["Location"]
    assert "Nenhuma solicitação aguardando" in get(admin, "/autorizacoes").get_data(as_text=True)

    minhas = get(logado(app, "webt_r3"), "/autorizacoes").get_data(as_text=True)
    assert "Minhas solicitações" in minhas and "Executada" in minhas and "Aguardando decisão" not in minhas
