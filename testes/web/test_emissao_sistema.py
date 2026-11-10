"""Telas do Incremento 5 no navegador: dados da clínica, modelos, documentos da ficha, relatórios e pedidos do titular,
pelo teclado e com o axe-core sem violação (RNF-406). Com SAR_CAPTURAS apontando para uma pasta, guarda as capturas
nas larguras de referência (1900, 1100 e 700), para revisão do leiaute."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import dados_completos, pessoa
from testes.apoio.cadastro import montar as montar_cadastro
from testes.apoio.fabrica import Fabrica
from testes.apoio.modelos import conversor_no_ar
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema

LARGURAS = (1900, 1100, 700)


def capturar(page: Page, nome: str) -> None:
    pasta = os.environ.get("SAR_CAPTURAS")
    if not pasta:
        return
    for largura in LARGURAS:
        page.set_viewport_size({"width": largura, "height": 1000})
        page.screenshot(path=str(Path(pasta) / f"{nome}-{largura}.png"), full_page=True)
    page.set_viewport_size({"width": 1280, "height": 900})


@pytest.fixture
def limpeza(
    cadastro_zerado: dict[str, int], criar_usuario: CriarUsuario, engine_migracao: Engine
) -> Iterator[dict[str, int]]:
    """Depois de criar_usuario: as emissões saem antes dos usuários que as registraram."""
    yield cadastro_zerado
    with engine_migracao.begin() as c:
        for tabela in ("modelo_documento", "instituicao", "emissao_documento", "requisicao_titular"):
            c.execute(text(f"DELETE FROM {tabela}"))  # noqa: S608 — nomes fixos do teste


@pytest.mark.requisito("RNF-406", "RF-1201", "RF-801", "RF-901", "RF-1009", "DD-42")
def test_telas_do_incremento_5_pelo_teclado_sem_violacao(
    limpeza: dict[str, int], criar_usuario: CriarUsuario, endereco: str, page: Page, engine_web: Engine,
    fabrica: Fabrica,
) -> None:  # fmt: skip
    conversor_no_ar()
    criar_usuario("sise_admin", perfil="administracao")
    dados = dados_completos(fabrica)
    pid = montar_cadastro(engine_web).pacientes.criar(pessoa(limpeza), dados, date(2026, 10, 1))
    entrar_no_navegador(page, endereco, "sise_admin")

    page.get_by_role("link", name="Dados da clínica").click()
    sem_violacao(page)
    page.get_by_label("Nome da clínica").fill("Clínica Fictícia de Teste")
    page.get_by_label("Endereço (rua, número e bairro)").fill("Rua das Flores, 100 - Centro")
    page.get_by_label("CEP").fill("75803000")
    page.get_by_label("Município (GO)").select_option(label="Jataí")
    page.get_by_label("Telefone com DDD").fill("6436000000")
    page.get_by_label("Telefone com DDD").press("Enter")  # sem mouse
    expect(page.get_by_role("status")).to_contain_text("Dados da clínica salvos.")
    sem_violacao(page)
    capturar(page, "clinica")

    page.get_by_role("link", name="Modelos de documento").click()
    expect(page.get_by_role("heading", name="Crachá do paciente")).to_be_visible()
    sem_violacao(page)
    capturar(page, "modelos")

    page.goto(f"{endereco}/pacientes/{pid}")
    expect(page.get_by_role("heading", name="Documentos para imprimir")).to_be_visible()
    sem_violacao(page)
    capturar(page, "ficha-documentos")
    page.get_by_role("link", name="Registrar pedido do titular").click()
    sem_violacao(page)
    page.get_by_label("Confirmação e acesso aos dados").check()
    page.get_by_label("Como o pedido chegou").select_option("presencial")
    page.get_by_role("button", name="Registrar pedido").click()
    expect(page.get_by_role("status")).to_contain_text("Pedido registrado.")
    sem_violacao(page)
    capturar(page, "titular-pedido")
    page.get_by_role("link", name="Todos os pedidos").click()
    expect(page.get_by_role("table", name="Pedidos do titular")).to_contain_text(dados.nome or "")
    sem_violacao(page)
    capturar(page, "titular-lista")

    page.get_by_role("link", name="Relatórios").click()
    sem_violacao(page)
    capturar(page, "relatorios")
    page.get_by_role("link", name="Pacientes por sexo").click()
    page.get_by_role("button", name="Gerar relatório").click()
    expect(page.get_by_role("table", name="Pacientes por sexo")).to_contain_text("Total")
    sem_violacao(page)
    capturar(page, "relatorio-sexo")


@pytest.mark.requisito("RF-801", "RNF-206", "DD-43", "DD-84")
def test_documento_abre_na_aba_nova_sem_segunda_busca_ao_servidor(
    limpeza: dict[str, int], criar_usuario: CriarUsuario, endereco: str, page: Page, engine_web: Engine,
    fabrica: Fabrica,
) -> None:  # fmt: skip
    """Defeito do uso: o PDF do POST abria numa aba nova, o visualizador do navegador o buscava de novo por GET, e a
    emissão, que só aceita POST, respondia 405. O script entrega o PDF à aba pela memória (blob:)."""
    conversor_no_ar()
    criar_usuario("sise_admin2", perfil="administracao")
    pid = montar_cadastro(engine_web).pacientes.criar(pessoa(limpeza), dados_completos(fabrica), date(2026, 10, 1))
    entrar_no_navegador(page, endereco, "sise_admin2")
    page.goto(f"{endereco}/clinica")
    page.get_by_label("Nome da clínica").fill("Clínica Fictícia de Teste")
    page.get_by_label("Endereço (rua, número e bairro)").fill("Rua das Flores, 100 - Centro")
    page.get_by_label("CEP").fill("75803000")
    page.get_by_label("Município (GO)").select_option(label="Jataí")
    page.get_by_role("button", name="Salvar os dados").click()

    respostas: list[tuple[str, str, int]] = []
    baixados: list[str] = []  # o Chromium sem janela não tem visualizador de PDF: o blob: vira download
    page.context.on("response", lambda r: respostas.append((r.request.method, r.url, r.status)))
    page.context.on("page", lambda nova: nova.on("download", lambda d: baixados.append(d.url)))
    page.goto(f"{endereco}/pacientes/{pid}")
    page.get_by_role("button", name="Termo do cateter").click()
    for _ in range(150):
        if baixados:
            break
        page.wait_for_timeout(200)
    assert len(baixados) == 1 and baixados[0].startswith("blob:"), baixados
    emissoes = [(m, s) for m, u, s in respostas if "/emitir/" in u]
    assert emissoes == [("POST", 200)], emissoes  # uma só ida ao servidor, nenhum GET recusado
    with engine_web.connect() as c:
        assert c.execute(text("SELECT modelo FROM emissao_documento")).scalars().all() == ["DOC-02"]

    with page.context.expect_page() as outra:  # aviso: a mesma aba mostra a página do servidor
        page.get_by_role("button", name="Crachá").click()
    expect(outra.value.get_by_role("alert")).to_contain_text("O paciente não tem foto")
