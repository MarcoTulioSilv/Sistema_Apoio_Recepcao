from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from sar.nucleo.logs import FormatadorJson
from sar.web import CABECALHO_REQUISICAO, POLITICA_CONTEUDO, criar_app
from testes.apoio.vazamento import ColetorLogs

MODELOS = Path(__file__).resolve().parents[2] / "sar" / "web" / "modelos"


@pytest.mark.requisito("DD-09")
def test_saude_responde_com_politica_de_conteudo_estrita() -> None:
    resposta = criar_app().test_client().get("/saude")
    assert resposta.status_code == 200
    assert resposta.headers["Content-Security-Policy"] == POLITICA_CONTEUDO
    assert "unsafe-inline" not in POLITICA_CONTEUDO
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.requisito("DD-09")
@pytest.mark.parametrize("modelo", sorted(MODELOS.rglob("*.html")), ids=lambda p: p.name)
def test_modelos_sem_codigo_estilo_ou_recurso_externo(modelo: Path) -> None:
    html = modelo.read_text(encoding="utf-8")
    assert not re.search(r"\sstyle\s*=", html, re.I)
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.I)
    assert not re.search(r"<style", html, re.I)
    assert not re.search(r"(src|href)\s*=\s*[\"'](https?:)?//", html, re.I)


@pytest.mark.requisito("DD-81", "CT-LOG-04")
def test_cada_requisicao_tem_id_e_linha_de_log_sem_caminho() -> None:
    coletor = ColetorLogs()
    logging.getLogger("sar.web").addHandler(coletor)
    try:
        resposta = criar_app().test_client().get("/saude?nome=Maria")
    finally:
        logging.getLogger("sar.web").removeHandler(coletor)
    ident = resposta.headers[CABECALHO_REQUISICAO]
    assert re.fullmatch(r"[0-9a-f]{32}", ident)
    linha = json.loads(next(lin for lin in coletor.linhas if '"evento":"web.requisicao"' in lin))
    assert (linha["requisicao_id"], linha["resultado"]) == (ident, "200")
    assert "duracao_ms" in linha
    assert "saude" not in json.dumps(linha) and "Maria" not in json.dumps(linha)


@pytest.mark.requisito("RNF-624", "DD-81")
def test_erro_inesperado_responde_generico_e_loga_so_o_tipo(caplog: pytest.LogCaptureFixture) -> None:
    app = criar_app()

    @app.get("/falha")
    def falha() -> str:
        raise ValueError("Maria Fictício, CPF 52998224725")

    with caplog.at_level(logging.INFO):
        resposta = app.test_client().get("/falha")
    assert resposta.status_code == 500
    corpo = resposta.get_data(as_text=True)
    assert "Maria" not in corpo and "ValueError" not in corpo
    assert resposta.headers[CABECALHO_REQUISICAO] in corpo  # o código para o TI correlacionar
    linhas = [FormatadorJson("web").format(r) for r in caplog.records]
    assert any('"evento":"web.erro_inesperado"' in linha and '"erro":"ValueError"' in linha for linha in linhas)
    assert not any("Maria" in linha or "52998224725" in linha for linha in linhas)


@pytest.mark.requisito("DD-81")
def test_erro_http_segue_como_esta() -> None:
    assert criar_app().test_client().get("/nao-existe").status_code == 404
