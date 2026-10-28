"""Documentos no navegador (DDS §8.3 a §8.6): digitalização com um agente falso no loopback, foto pela câmera falsa do
Chromium, conferência e ficha, com teclado e axe-core (RNF-406) e sem erro de script (DD-09)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import httpx
import pytest
from playwright.sync_api import Browser, Page, Route, expect
from sqlalchemy import Engine

from agente_captura.captura import Captura
from agente_captura.envio import Enviador
from agente_captura.servidor import ServidorAgente
from sar.composicao import compor_worker
from sar.modulo_04_documentos.worker import ProcessadorIngestoes
from testes.apoio import corpus
from testes.apoio.acesso import CriarUsuario
from testes.apoio.agente import ScannerFalso
from testes.apoio.cadastro import INICIO, dados_completos, pessoa
from testes.apoio.cadastro import montar as montar_cadastro
from testes.apoio.documentos import AntimalwareFalso
from testes.apoio.fabrica import Fabrica
from testes.apoio.web import PASTAS
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema

AGENTE = "http://127.0.0.1:47830"


@pytest.fixture
def worker(engine_worker: Engine) -> ProcessadorIngestoes:
    return compor_worker(engine_worker, bytes(32), PASTAS, AntimalwareFalso(assinaturas_em=datetime.now(UTC)))


@pytest.fixture
def paciente(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica
) -> tuple[int, str]:
    dados = dados_completos(fabrica)
    pid = montar_cadastro(engine_web).pacientes.criar(pessoa(cadastro_zerado), dados, INICIO)
    return pid, dados.nome or ""


def _vigiar(page: Page) -> list[str]:
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erros.append(str(e)))
    return erros


@pytest.mark.requisito("RNF-406", "RF-712", "DD-98", "DD-39")
def test_digitalizar_pelo_agente_conferir_e_ver_na_ficha(
    criar_usuario: CriarUsuario, paciente: tuple[int, str], endereco: str, page: Page, worker: ProcessadorIngestoes,
    sem_tesseract: None,
) -> None:  # fmt: skip
    pid, nome = paciente
    erros = _vigiar(page)

    def agente_falso(route: Route) -> None:
        """O que o agente faz (§8.5): envia as páginas pelo token e conclui; aqui o worker processa na hora."""
        pedido = json.loads(route.request.post_data or "{}")
        assert pedido["papel"] == "alimentador" and set(pedido) == {"ingestao", "token", "papel"}
        cabecalho = {"Authorization": f"Bearer {pedido['token']}"}
        with httpx.Client(base_url=endereco) as servidor:
            for numero, semente in ((1, 1), (2, 2)):
                pagina = corpus.em_formato(corpus.pagina_ficticia(semente), "PNG")
                url = f"/captura/ingestoes/{pedido['ingestao']}/paginas/{numero}"
                assert servidor.put(url, content=pagina, headers=cabecalho).status_code == 204
            concluir = f"/captura/ingestoes/{pedido['ingestao']}/concluir"
            assert servidor.post(concluir, json={"paginas": 2}, headers=cabecalho).status_code == 204
        worker.processar_proxima()
        route.fulfill(status=200, content_type="application/json", body='{"paginas": 2}',
                      headers={"Access-Control-Allow-Origin": endereco})  # fmt: skip

    page.route(f"{AGENTE}/capturar", agente_falso)
    criar_usuario("sistdoc_rec")
    entrar_no_navegador(page, endereco, "sistdoc_rec")
    page.wait_for_load_state("networkidle")  # a tela inicial termina de carregar antes de sair dela
    page.goto(f"{endereco}/pacientes/{pid}")
    page.get_by_role("link", name="Digitalizar documento").click()
    expect(page.get_by_text("O documento vai para")).to_be_visible()
    sem_violacao(page)
    page.get_by_label("Tipo de documento").select_option("cartao_sus")
    page.get_by_label("No alimentador (várias folhas)").check()
    page.get_by_role("button", name="Digitalizar").click()
    conferir = page.get_by_role("link", name="Conferir agora")
    expect(conferir).to_be_visible(timeout=15000)
    sem_violacao(page)
    conferir.click()

    expect(page.get_by_role("heading", name="Conferir: Cartão do SUS")).to_be_visible()
    expect(page.locator(".destaque-paciente")).to_contain_text(nome)
    expect(page.get_by_alt_text("Página 2 de 2 do documento capturado")).to_be_visible()
    sem_violacao(page)
    page.get_by_role("button", name="Guardar o documento").click()
    expect(page.get_by_role("status")).to_contain_text("Documento guardado.")
    documentos = page.get_by_role("table", name="Documentos do paciente")
    expect(documentos).to_contain_text("Cartão do SUS")
    sem_violacao(page)
    documentos.get_by_role("link", name="Abrir Cartão do SUS").click()
    expect(page.get_by_alt_text("Cartão do SUS, página 2 de 2")).to_be_visible()
    sem_violacao(page)
    assert erros == []


@pytest.mark.requisito("DD-39")
def test_agente_ausente_avisa_a_recepcionista(
    criar_usuario: CriarUsuario, paciente: tuple[int, str], endereco: str, page: Page
) -> None:
    pid, _ = paciente
    page.route(f"{AGENTE}/capturar", lambda route: route.abort("connectionrefused"))
    criar_usuario("sistdoc_sem")
    entrar_no_navegador(page, endereco, "sistdoc_sem")
    page.wait_for_load_state("networkidle")  # a tela inicial termina de carregar antes de sair dela
    page.goto(f"{endereco}/documentos/digitalizar/{pid}")
    page.get_by_label("Tipo de documento").select_option("comprovante_endereco")
    page.get_by_role("button", name="Digitalizar").click()
    expect(page.get_by_role("alert")).to_contain_text("O programa de digitalização não respondeu nesta estação")
    expect(page.get_by_role("button", name="Cancelar")).to_be_visible()
    page.get_by_role("button", name="Cancelar").click()
    expect(page.get_by_role("status")).to_contain_text("Cancelado")


# ------------------------------------------------------------------ câmera (AD-18)
@pytest.mark.requisito("RF-711", "AD-18", "SEG-10")
def test_foto_pela_camera_ate_a_conferencia(
    criar_usuario: CriarUsuario, paciente: tuple[int, str], endereco: str, navegador: Browser,
    worker: ProcessadorIngestoes,
) -> None:  # fmt: skip
    pid, nome = paciente
    contexto = navegador.new_context(permissions=["camera"])
    page = contexto.new_page()
    erros = _vigiar(page)
    criar_usuario("sistdoc_cam")
    entrar_no_navegador(page, endereco, "sistdoc_cam")
    page.wait_for_load_state("networkidle")  # a tela inicial termina de carregar antes de sair dela
    page.goto(f"{endereco}/documentos/foto/{pid}")
    sem_violacao(page)
    page.get_by_role("button", name="Abrir a câmera").click()
    expect(page.get_by_role("status")).to_contain_text("Câmera aberta")
    page.get_by_role("button", name="Tirar a foto").click()
    expect(page.get_by_alt_text("Foto tirada, antes de enviar")).to_be_visible()
    page.get_by_role("button", name="Usar esta foto").click()
    expect(page.locator("[data-ingestao]")).to_be_visible()
    worker.processar_proxima()
    page.get_by_role("link", name="Conferir agora").click(timeout=15000)
    expect(page.locator(".destaque-paciente")).to_contain_text(nome)
    page.get_by_role("button", name="Guardar o documento").click()
    expect(page.get_by_role("table", name="Documentos do paciente")).to_contain_text("Foto do paciente")

    # Na edição em tela larga, a foto de verdade fica nas duas primeiras linhas. Antes, o tamanho próprio da imagem
    # esticava as linhas até a altura original dela.
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(f"{endereco}/pacientes/{pid}/editar")
    foto = page.get_by_alt_text("Foto atual do paciente")
    expect(foto).to_be_visible()
    caixa = foto.bounding_box()
    topo = page.locator("label[for=nome]").bounding_box()
    base = page.locator("#nascimento").bounding_box()
    assert caixa and topo and base
    assert caixa["y"] + caixa["height"] <= base["y"] + base["height"] + 2
    assert caixa["height"] >= base["y"] + base["height"] - topo["y"] - 30  # e preenche as duas linhas
    sem_violacao(page)
    assert erros == []
    contexto.close()


# ------------------------------------------------------------------ ponta a ponta com o agente de verdade
@pytest.mark.requisito("RNF-208", "DD-39", "DD-77", "DD-94", "DD-100")
def test_agente_de_verdade_ate_a_conferencia(
    criar_usuario: CriarUsuario, paciente: tuple[int, str], endereco: str, page: Page, worker: ProcessadorIngestoes,
    sem_tesseract: None,
) -> None:  # fmt: skip
    """O agente real no loopback (só o scanner é falso): a página chama, ele digitaliza, converte e envia pelo token
    ao SAR em teste (HTTP de desenvolvimento, DD-100); o worker processa; a conferência abre."""
    pid, nome = paciente
    erros = _vigiar(page)
    captura = Captura(ScannerFalso(folhas=2), Enviador(endereco, None))
    agente = ServidorAgente(47830, endereco, captura.executar)
    parar = threading.Event()

    def consumir_fila() -> None:
        while not parar.is_set():
            if not worker.processar_proxima():
                parar.wait(0.2)

    for alvo in (agente.serve_forever, consumir_fila):
        threading.Thread(target=alvo, daemon=True).start()
    try:
        criar_usuario("sistdoc_ag")
        entrar_no_navegador(page, endereco, "sistdoc_ag")
        page.wait_for_load_state("networkidle")
        page.goto(f"{endereco}/documentos/digitalizar/{pid}")
        page.get_by_label("Tipo de documento").select_option("comprovante_endereco")
        page.get_by_label("No alimentador (várias folhas)").check()
        page.get_by_role("button", name="Digitalizar").click()
        page.get_by_role("link", name="Conferir agora").click(timeout=20000)
        expect(page.locator(".destaque-paciente")).to_contain_text(nome)
        expect(page.get_by_alt_text("Página 2 de 2 do documento capturado")).to_be_visible()
        page.get_by_role("button", name="Guardar o documento").click()
        expect(page.get_by_role("table", name="Documentos do paciente")).to_contain_text("Comprovante de endereço")
    finally:
        parar.set()
        agente.shutdown()
        agente.server_close()
    assert erros == []
