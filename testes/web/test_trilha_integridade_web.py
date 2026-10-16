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
from sar.nucleo.portas import Autorizacao
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
        self, uow: UnidadeDeTrabalho, autor: Contexto, autorizacao: Autorizacao, parametros: Mapping[str, Any]
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
    assert "Anular o cadastro 42" in fila
    solicitacao = re.search(r'data-solicitacao="([0-9a-f]{32})"', fila)
    assert solicitacao is not None and f'href="/autorizacoes/{solicitacao.group(1)}"' in fila  # botão Analisar
    analise = get(admin, f"/autorizacoes/{solicitacao.group(1)}").get_data(as_text=True)
    assert "Cadastro duplicado" in analise and 'value="aprovar"' in analise and 'value="negar"' in analise
    sem_motivo = post(admin, f"/autorizacoes/{solicitacao.group(1)}/recusar", {"motivo": ""})
    corpo = sem_motivo.get_data(as_text=True)
    assert "Para negar, o motivo é obrigatório" in corpo and "Análise do pedido" in corpo  # volta à análise
    aprovada = post(admin, f"/autorizacoes/{solicitacao.group(1)}/aprovar", {"motivo": ""})
    assert "resultado=executada" in aprovada.headers["Location"]
    assert "Nenhuma solicitação aguardando" in get(admin, "/autorizacoes").get_data(as_text=True)

    minhas = get(logado(app, "webt_r3"), "/autorizacoes").get_data(as_text=True)
    assert "Minhas solicitações" in minhas and "Executada" in minhas and "Aguardando decisão" not in minhas


@pytest.mark.requisito("RF-1008", "DEC-42", "RNF-623")
def test_tela_de_analise_do_pedido(
    criar_usuario: CriarUsuario, engine_web: Engine, monkeypatch: pytest.MonkeyPatch, limpar: None
) -> None:
    monkeypatch.setitem(sar.composicao.EXECUTORES_AUTORIZAVEIS, ANULAR, ExecutorFalso())
    criar_usuario("webt_adm4", perfil="administracao")
    recepcao = criar_usuario("webt_r4")
    criar_usuario("webt_r5")
    criar_usuario("webt_ti4", perfil="ti")
    pedidos = ServicoAutorizacoes(
        montar_executor(engine_web, montar_barramento(RelogioSistema())), ServicoAuditoria(), {ANULAR: ExecutorFalso()}
    )
    contexto = Contexto(recepcao, Perfil.RECEPCAO, None, "10.0.0.5", datetime.now(UTC), "d" * 32)
    primeiro = pedidos.solicitar(contexto, ANULAR, "42", {"paciente_id": 42}, "Cadastro duplicado")
    segundo = pedidos.solicitar(contexto, ANULAR, "43", {"paciente_id": 43}, "Paciente errado")
    app = montar(engine_web)

    autora = logado(app, "webt_r4")
    minhas = get(autora, "/autorizacoes").get_data(as_text=True)
    assert f'href="/autorizacoes/{primeiro}"' in minhas and "Ver detalhes" in minhas
    detalhe = get(autora, f"/autorizacoes/{primeiro}").get_data(as_text=True)
    assert "Cadastro duplicado" in detalhe and "Cancelar este pedido" in detalhe and 'value="aprovar"' not in detalhe

    admin = logado(app, "webt_adm4")
    reprovado = post(admin, f"/autorizacoes/{primeiro}/recusar", {"motivo": "Não é duplicata: são irmãos gêmeos"})
    assert "resultado=recusada" in reprovado.headers["Location"]
    assert "Solicitação negada." in get(admin, reprovado.headers["Location"]).get_data(as_text=True)
    decidido = get(autora, f"/autorizacoes/{primeiro}").get_data(as_text=True)
    assert "Negada" in decidido and "Não é duplicata: são irmãos gêmeos" in decidido
    assert "Cancelar este pedido" not in decidido

    post(autora, f"/autorizacoes/{segundo}/cancelar", {})
    assert "Cancelada" in get(autora, f"/autorizacoes/{segundo}").get_data(as_text=True)

    assert get(logado(app, "webt_r5"), f"/autorizacoes/{primeiro}").status_code == 404  # não é dela
    assert get(admin, "/autorizacoes/" + "0" * 32).status_code == 404
    assert get(admin, "/autorizacoes/nao-e-hex").status_code == 404
    assert get(logado(app, "webt_ti4"), f"/autorizacoes/{primeiro}").status_code == 403


@pytest.mark.requisito("RF-1008", "DEC-42")
def test_decisao_em_dois_passos_sem_javascript(
    criar_usuario: CriarUsuario, engine_web: Engine, monkeypatch: pytest.MonkeyPatch, limpar: None
) -> None:
    """A escolha não decide: a tela volta com o diálogo de confirmação aberto, na cor da escolha, e só o botão do
    diálogo (confirmado=1) decide. Negar exige o motivo (§5.3)."""
    monkeypatch.setitem(sar.composicao.EXECUTORES_AUTORIZAVEIS, ANULAR, ExecutorFalso())
    criar_usuario("webt_adm6", perfil="administracao")
    recepcao = criar_usuario("webt_r6")
    pedidos = ServicoAutorizacoes(
        montar_executor(engine_web, montar_barramento(RelogioSistema())), ServicoAuditoria(), {ANULAR: ExecutorFalso()}
    )
    contexto = Contexto(recepcao, Perfil.RECEPCAO, None, "10.0.0.5", datetime.now(UTC), "d" * 32)
    negar = pedidos.solicitar(contexto, ANULAR, "44", {"paciente_id": 44}, "Duplicado")
    aprovar = pedidos.solicitar(contexto, ANULAR, "45", {"paciente_id": 45}, "Duplicado")
    admin = logado(montar(engine_web), "webt_adm6")

    sem_escolha = post(admin, f"/autorizacoes/{negar}/decidir", {}).get_data(as_text=True)
    assert "Escolha aprovar ou negar antes de confirmar." in sem_escolha
    passo = post(admin, f"/autorizacoes/{negar}/decidir", {"decisao": "negar"}).get_data(as_text=True)
    assert re.search(r'id="confirmar-decisao"[^>]*\bopen\b', passo) and "Negar este pedido?" in passo
    assert 'class="btn-urgente" type="submit" name="confirmado"' in passo and "required" in passo
    sem_motivo = post(admin, f"/autorizacoes/{negar}/decidir", {"decisao": "negar", "confirmado": "1", "motivo": " "})
    assert "Para negar, o motivo é obrigatório" in sem_motivo.get_data(as_text=True)
    negado = post(admin, f"/autorizacoes/{negar}/decidir", {"decisao": "negar", "confirmado": "1", "motivo": "Não"})
    assert "resultado=recusada" in negado.headers["Location"]

    passo = post(admin, f"/autorizacoes/{aprovar}/decidir", {"decisao": "aprovar"}).get_data(as_text=True)
    assert "Aprovar este pedido?" in passo and 'class="btn-aprovar" type="submit" name="confirmado"' in passo
    aprovado = post(admin, f"/autorizacoes/{aprovar}/decidir", {"decisao": "aprovar", "confirmado": "1"})
    assert "resultado=executada" in aprovado.headers["Location"]  # motivo opcional ao aprovar


@pytest.mark.requisito("RF-1008", "DEC-42")
def test_finalizadas_da_mais_recente_para_a_mais_antiga(
    criar_usuario: CriarUsuario, engine_web: Engine, monkeypatch: pytest.MonkeyPatch, limpar: None
) -> None:
    monkeypatch.setitem(sar.composicao.EXECUTORES_AUTORIZAVEIS, ANULAR, ExecutorFalso())
    admin_id = criar_usuario("webt_adm7", perfil="administracao")
    rita, ana = criar_usuario("webt_r7"), criar_usuario("webt_r8")
    servico = ServicoAutorizacoes(
        montar_executor(engine_web, montar_barramento(RelogioSistema())), ServicoAuditoria(), {ANULAR: ExecutorFalso()}
    )

    def em(usuario: int, perfil: Perfil, hora: int) -> Contexto:
        return Contexto(usuario, perfil, None, "10.0.0.5", datetime(2026, 10, 14, hora, 0, tzinfo=UTC), "d" * 32)

    antiga = servico.solicitar(em(rita, Perfil.RECEPCAO, 10), ANULAR, "50", {"paciente_id": 50}, "Pedido A")
    meio = servico.solicitar(em(ana, Perfil.RECEPCAO, 10), ANULAR, "51", {"paciente_id": 51}, "Pedido B")
    nova = servico.solicitar(em(rita, Perfil.RECEPCAO, 10), ANULAR, "52", {"paciente_id": 52}, "Pedido C")
    pendente = servico.solicitar(em(rita, Perfil.RECEPCAO, 10), ANULAR, "53", {"paciente_id": 53}, "Pedido D")
    servico.recusar(em(admin_id, Perfil.ADMINISTRACAO, 11), antiga, "Não")
    servico.aprovar(em(admin_id, Perfil.ADMINISTRACAO, 12), meio)
    servico.cancelar(em(rita, Perfil.RECEPCAO, 13), nova)
    app = montar(engine_web)

    tela = get(logado(app, "webt_adm7"), "/autorizacoes").get_data(as_text=True)
    ordem = re.findall(r'data-finalizada="([0-9a-f]{32})"', tela)
    assert ordem == [nova, meio, antiga]  # cancelada às 13h, aprovada às 12h, negada às 11h
    assert "Finalizadas" in tela and f'data-solicitacao="{pendente}"' in tela  # a fila continua acima
    assert f'data-finalizada="{pendente}"' not in tela

    da_rita = get(logado(app, "webt_r7"), "/autorizacoes").get_data(as_text=True)
    assert re.findall(r'data-finalizada="([0-9a-f]{32})"', da_rita) == [nova, antiga]  # só as dela
    assert "Minhas solicitações finalizadas" in da_rita and f'data-minha="{pendente}"' in da_rita
    assert "Negada" in da_rita and "Cancelada" in da_rita
