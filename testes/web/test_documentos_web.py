"""Telas de documentos pela web, com o banco de testes (DDS §8.3 a §8.6): rotas de captura pelo token (DD-94),
acompanhamento, fila e tela de conferência (RF-704, RF-712), campos lidos levados ao cadastro (DD-40), documentos na
ficha, páginas como imagem (SEG-19), revinculação (RF-713) e permissões por perfil (DEC-55)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine

from sar.composicao import compor_worker
from sar.modulo_04_documentos.worker import ProcessadorIngestoes
from testes.apoio import corpus
from testes.apoio.acesso import CriarUsuario
from testes.apoio.documentos import AntimalwareFalso
from testes.apoio.fabrica import Fabrica, PacienteFicticio
from testes.apoio.web import ORIGEM, PASTAS, entrar, get, montar, post

pytestmark = pytest.mark.integracao


def pagina(semente: int) -> bytes:
    return corpus.em_formato(corpus.pagina_ficticia(semente), "PNG")


@pytest.fixture
def app(engine_web: Engine, criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int]) -> Flask:
    """O cadastro sai antes dos usuários criados no teste, que as ingestões referenciam."""
    return montar(engine_web)


@pytest.fixture
def worker(engine_worker: Engine) -> Iterator[ProcessadorIngestoes]:
    # O worker da web usa o relógio do sistema: as assinaturas do antimalware falso são de agora.
    yield compor_worker(engine_worker, bytes(32), PASTAS, AntimalwareFalso(assinaturas_em=datetime.now(UTC)))


def cliente(app: Flask, criar_usuario: CriarUsuario, perfil: str) -> FlaskClient:
    login = f"webdoc_{perfil[:6]}"
    criar_usuario(login, perfil=perfil)
    c = app.test_client()
    assert entrar(c, login).status_code == 302
    return c


def novo_paciente(c: FlaskClient, fabrica: Fabrica) -> tuple[int, str]:
    prontuario = fabrica.prontuario()
    dados = {"nome": fabrica.nome(), "prontuario": prontuario, "inicio": "2026-01-05", "acao": "paciente"}
    achado = re.search(r"/pacientes/(\d+)", post(c, "/cadastro/novo", dados).headers.get("Location", ""))
    assert achado
    return int(achado.group(1)), prontuario


def abrir(c: FlaskClient, paciente_id: int, tipo: str = "cartao_sus", **extra: str) -> dict[str, str]:
    dados = {"paciente_id": str(paciente_id), "tipo": tipo, "origem": "scanner", **extra}
    resposta = post(c, "/documentos/ingestoes", dados)
    assert resposta.status_code == 201, resposta.get_data(as_text=True)
    corpo: dict[str, str] = resposta.get_json()
    return corpo


def enviar(app: Flask, ingestao: dict[str, str], paginas: list[bytes]) -> None:
    """Como o agente faz: sem cookie e sem Origin, só o token (DD-94)."""
    agente = app.test_client()
    cabecalho = {"Authorization": f"Bearer {ingestao['token']}"}
    for numero, conteudo in enumerate(paginas, start=1):
        resposta = agente.put(f"/captura/ingestoes/{ingestao['id']}/paginas/{numero}", data=conteudo,
                              headers=cabecalho, base_url=ORIGEM)  # fmt: skip
        assert resposta.status_code == 204, resposta.get_data(as_text=True)
    concluida = agente.post(f"/captura/ingestoes/{ingestao['id']}/concluir", json={"paginas": len(paginas)},
                            headers=cabecalho, base_url=ORIGEM)  # fmt: skip
    assert concluida.status_code == 204


def capturado(app: Flask, c: FlaskClient, worker: ProcessadorIngestoes, paciente_id: int, tipo: str,
              paginas: list[bytes]) -> str:  # fmt: skip
    ingestao = abrir(c, paciente_id, tipo)
    enviar(app, ingestao, paginas)
    assert worker.processar_proxima()
    return ingestao["id"]


# ------------------------------------------------------------------ rotas de captura (DD-94)
@pytest.mark.requisito("DD-94", "DD-84", "SEG-01", "DD-05")
def test_captura_pelo_token_sem_cookie_nem_cors(app: Flask, criar_usuario: CriarUsuario, fabrica: Fabrica) -> None:
    recepcao = cliente(app, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    assert post(recepcao, "/documentos/ingestoes", {"paciente_id": str(pid)}, origem=None).status_code == 403
    ingestao = abrir(recepcao, pid)
    agente = app.test_client()
    url = f"/captura/ingestoes/{ingestao['id']}/paginas/1"
    errado = agente.put(url, data=b"x", headers={"Authorization": "Bearer outro"}, base_url=ORIGEM)
    assert errado.status_code == 403 and errado.get_json() == {"erro": "acesso"}
    assert agente.put(url, data=b"x", base_url=ORIGEM).status_code == 403  # sem token
    inexistente = agente.put("/captura/ingestoes/" + "0" * 32 + "/paginas/1", data=b"x",
                             headers={"Authorization": f"Bearer {ingestao['token']}"}, base_url=ORIGEM)  # fmt: skip
    assert inexistente.status_code == 403  # não revela se a ingestão existe
    vazia = agente.put(url, data=b"", headers={"Authorization": f"Bearer {ingestao['token']}"}, base_url=ORIGEM)
    assert vazia.status_code == 422 and vazia.get_json() == {"erro": "arquivo.vazio"}
    enviar(app, ingestao, [pagina(1)])
    repetida = agente.put(url, data=b"x", headers={"Authorization": f"Bearer {ingestao['token']}"}, base_url=ORIGEM)
    assert repetida.status_code == 403  # o token deixou de valer na conclusão
    assert "Access-Control-Allow-Origin" not in repetida.headers


# ------------------------------------------------------------------ acompanhamento e conferência
@pytest.mark.requisito("RF-712", "RF-701", "SEG-19", "DD-98")
def test_digitalizar_acompanhar_conferir_e_guardar(
    app: Flask, criar_usuario: CriarUsuario, fabrica: Fabrica, worker: ProcessadorIngestoes, sem_tesseract: None
) -> None:
    recepcao = cliente(app, criar_usuario, "recepcao")
    pid, prontuario = novo_paciente(recepcao, fabrica)
    tela = get(recepcao, f"/documentos/digitalizar/{pid}")
    html = tela.get_data(as_text=True)
    assert 'data-agente="http://127.0.0.1:47830"' in html and "Cartão do SUS" in html and "Foto do paciente" not in html
    assert "connect-src 'self' http://127.0.0.1:47830;" in tela.headers["Content-Security-Policy"]

    ingestao = abrir(recepcao, pid)
    assert "Esperando as páginas" in get(recepcao, ingestao["situacao"]).get_data(as_text=True)
    enviar(app, ingestao, [pagina(1), pagina(2)])
    worker.processar_proxima()
    situacao = get(recepcao, ingestao["situacao"]).get_data(as_text=True)
    assert "data-final" in situacao and f"/documentos/conferencia/{ingestao['id']}" in situacao

    fila = get(recepcao, "/documentos/conferencia").get_data(as_text=True)
    assert prontuario in fila and "Cartão do SUS" in fila
    conferencia = get(recepcao, f"/documentos/conferencia/{ingestao['id']}").get_data(as_text=True)
    assert "Este documento vai para" in conferencia and conferencia.count('class="pagina-documento"') == 2
    imagem = get(recepcao, f"/documentos/conferencia/{ingestao['id']}/paginas/1")
    assert imagem.mimetype == "image/jpeg" and imagem.headers["Cache-Control"] == "no-store"
    assert imagem.headers["X-Content-Type-Options"] == "nosniff"

    guardado = post(recepcao, f"/documentos/conferencia/{ingestao['id']}/incorporar", {})
    assert guardado.status_code == 302 and "resultado=documento" in guardado.headers["Location"]
    ficha = get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)
    [documento] = re.findall(r'data-documento="([0-9a-f]{32})"', ficha)
    assert "Documento guardado." in get(recepcao, guardado.headers["Location"]).get_data(as_text=True)
    ver = get(recepcao, f"/documentos/paciente/{pid}/{documento}").get_data(as_text=True)
    assert ver.count('class="pagina-documento"') == 2 and "Baixar o arquivo" not in ver
    assert get(recepcao, f"/documentos/{documento}/paginas/2").mimetype == "image/jpeg"
    assert get(recepcao, f"/documentos/{documento}/baixar").status_code == 403  # só a administração (P-17)
    assert prontuario not in get(recepcao, "/documentos/conferencia").get_data(as_text=True)


@pytest.mark.requisito("DD-40", "RF-703", "RF-704", "SEG-26")
def test_campo_lido_confirmado_vai_ao_cadastro(
    app: Flask, criar_usuario: CriarUsuario, fabrica: Fabrica, worker: ProcessadorIngestoes,
    tesseract_falso: PacienteFicticio,
) -> None:  # fmt: skip
    recepcao = cliente(app, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    ingestao_id = capturado(app, recepcao, worker, pid, "cartao_sus", [pagina(1)])
    tela = get(recepcao, f"/documentos/conferencia/{ingestao_id}").get_data(as_text=True)
    assert tesseract_falso.cns in tela and 'name="usar" value="cns"' in tela
    guardado = post(recepcao, f"/documentos/conferencia/{ingestao_id}/incorporar", {"usar": "cns"})
    assert "resultado=documento" in guardado.headers["Location"]
    assert tesseract_falso.cns in get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)


@pytest.mark.requisito("RF-712", "SEG-12")
def test_rejeicao_na_conferencia(
    app: Flask, criar_usuario: CriarUsuario, fabrica: Fabrica, worker: ProcessadorIngestoes, sem_tesseract: None
) -> None:
    recepcao = cliente(app, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    ingestao_id = capturado(app, recepcao, worker, pid, "cartao_sus", [pagina(1)])
    sem_motivo = post(recepcao, f"/documentos/conferencia/{ingestao_id}/rejeitar", {"motivo": ""})
    assert "Escolha o motivo da rejeição." in sem_motivo.get_data(as_text=True)
    rejeitado = post(recepcao, f"/documentos/conferencia/{ingestao_id}/rejeitar", {"motivo": "ilegivel"})
    assert rejeitado.headers["Location"].endswith("resultado=rejeitado")
    encerrada = get(recepcao, f"/documentos/conferencia/{ingestao_id}")
    assert encerrada.status_code == 302 and "resultado=encerrada" in encerrada.headers["Location"]


# ------------------------------------------------------------------ ficha, revinculação e pedidos
@pytest.mark.requisito("RF-713", "DEC-55", "P-17", "DD-04", "RF-1004")
def test_ficha_revinculacao_e_permissoes(
    app: Flask, criar_usuario: CriarUsuario, fabrica: Fabrica, worker: ProcessadorIngestoes, sem_tesseract: None
) -> None:
    recepcao = cliente(app, criar_usuario, "recepcao")
    errado, _ = novo_paciente(recepcao, fabrica)
    certo, prontuario_certo = novo_paciente(recepcao, fabrica)
    post(recepcao, f"/documentos/conferencia/{capturado(app, recepcao, worker, errado, 'cartao_sus', [pagina(1)])}"
         "/incorporar", {})  # fmt: skip
    [documento] = re.findall(
        r'data-documento="([0-9a-f]{32})"', get(recepcao, f"/pacientes/{errado}").get_data(as_text=True)
    )

    sem_destino = post(recepcao, f"/documentos/paciente/{errado}/{documento}/revincular",
                       {"prontuario": "999999999", "motivo": "Paciente errado"})  # fmt: skip
    assert "Não há paciente com esse prontuário." in sem_destino.get_data(as_text=True)
    passado = post(recepcao, f"/documentos/paciente/{errado}/{documento}/revincular",
                   {"prontuario": prontuario_certo, "motivo": "Paciente errado"})  # fmt: skip
    assert passado.headers["Location"].startswith(f"/pacientes/{certo}")
    assert documento in get(recepcao, f"/pacientes/{certo}").get_data(as_text=True)
    assert documento not in get(recepcao, f"/pacientes/{errado}").get_data(as_text=True)

    visualizador = cliente(app, criar_usuario, "visualizador")
    ficha = get(visualizador, f"/pacientes/{certo}").get_data(as_text=True)
    assert documento in ficha and "Digitalizar documento" not in ficha
    assert get(visualizador, f"/documentos/{documento}/paginas/1").status_code == 200
    assert get(visualizador, "/documentos/conferencia").status_code == 403
    for perfil in ("enfermagem", "ti"):
        outro = cliente(app, criar_usuario, perfil)
        assert get(outro, f"/documentos/{documento}/paginas/1").status_code == 403, perfil
        assert get(outro, "/documentos/conferencia").status_code == 403, perfil

    admin = cliente(app, criar_usuario, "administracao")
    baixado = get(admin, f"/documentos/{documento}/baixar")
    assert baixado.mimetype == "application/pdf" and "attachment" in baixado.headers["Content-Disposition"]
    cedo = post(admin, f"/documentos/paciente/{certo}/{documento}/descarte", {"motivo": "Fim do prazo"})
    assert "O prazo de guarda deste documento ainda não venceu." in cedo.get_data(as_text=True)  # INV-13


@pytest.mark.requisito("SEG-12")
def test_conferencia_ja_encerrada_volta_a_fila(
    app: Flask, criar_usuario: CriarUsuario, fabrica: Fabrica, worker: ProcessadorIngestoes, sem_tesseract: None
) -> None:
    """Outra estação concluiu antes: guardar ou rejeitar de novo volta à fila com o aviso, nunca erro 500."""
    recepcao = cliente(app, criar_usuario, "recepcao")
    pid, _ = novo_paciente(recepcao, fabrica)
    ingestao_id = capturado(app, recepcao, worker, pid, "cartao_sus", [pagina(1)])
    post(recepcao, f"/documentos/conferencia/{ingestao_id}/incorporar", {})
    for acao, dados in (("incorporar", {}), ("rejeitar", {"motivo": ""}), ("rejeitar", {"motivo": "ilegivel"})):
        resposta = post(recepcao, f"/documentos/conferencia/{ingestao_id}/{acao}", dados)
        assert resposta.status_code == 302 and "resultado=encerrada" in resposta.headers["Location"], acao
