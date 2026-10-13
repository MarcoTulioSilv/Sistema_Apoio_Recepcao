"""Montagem do processo web pelo sar/wsgi.py, com o banco de testes (DD-85)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from sar.wsgi import montar
from testes.apoio.acesso import CriarUsuario

pytestmark = pytest.mark.integracao


@pytest.fixture
def logging_restaurado() -> Iterator[None]:
    """O montar() liga o formato de log da DD-81 na raiz; o teste devolve o logging como estava."""
    raiz = logging.getLogger()
    handlers, nivel, fabrica = list(raiz.handlers), raiz.level, logging.getLogRecordFactory()
    yield
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)
    for handler in handlers:
        raiz.addHandler(handler)
    raiz.setLevel(nivel)
    logging.setLogRecordFactory(fabrica)
    logging.captureWarnings(False)


@pytest.mark.requisito("DD-85")
def test_login_de_superusuario_inexistente_impede_a_subida(
    criar_usuario: CriarUsuario, monkeypatch: pytest.MonkeyPatch, logging_restaurado: None
) -> None:
    """Defeito encontrado em uso: um login com a grafia errada (marco.apoio no lugar de marco_apoio) era
    ignorado em silêncio, e a pessoa ficava sem o seletor de perfil sem saber por quê."""
    criar_usuario("wsgi_super")
    monkeypatch.setenv("SAR_AMBIENTE", "desenvolvimento")
    monkeypatch.setenv("SAR_SUPERUSUARIOS", "wsgi_super,wsgi.super")
    with pytest.raises(RuntimeError) as erro:
        montar()
    assert "wsgi.super" in str(erro.value) and "wsgi_super," not in str(erro.value)


@pytest.mark.requisito("DD-85")
def test_superusuarios_existentes_viram_ids_na_subida(
    criar_usuario: CriarUsuario, monkeypatch: pytest.MonkeyPatch, logging_restaurado: None
) -> None:
    uid = criar_usuario("wsgi_super2")
    monkeypatch.setenv("SAR_AMBIENTE", "desenvolvimento")
    monkeypatch.setenv("SAR_SUPERUSUARIOS", " WSGI_SUPER2 ")  # espaço e maiúscula não atrapalham
    assert montar().config["SAR"].superusuarios == frozenset({uid})
