"""Apoio dos testes da web: os serviços montados como o sar/wsgi.py monta, e um cliente que já manda a origem
do SAR em todo POST (DD-84)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine
from werkzeug.test import TestResponse

from sar.composicao import compor
from sar.modulo_04_documentos.armazenamento import Pastas
from sar.nucleo.portas import Relogio
from sar.web import criar_app
from sar.web.configuracao import ConfigWeb, ServicosWeb
from testes.apoio.acesso import HASHER, SENHA
from testes.apoio.cadastro import ProvedorCepFalso

ORIGEM = "https://sar.teste"
_ARMAZENAMENTO = Path(tempfile.gettempdir()) / "sar-testes-web"
PASTAS = Pastas(_ARMAZENAMENTO / "cofre", _ARMAZENAMENTO / "quarentena")


def servicos_web(
    engine: Engine, provedor_cep: ProvedorCepFalso | None = None, relogio: Relogio | None = None
) -> ServicosWeb:
    """O provedor de CEP é sempre falso: nenhum teste acessa a internet. Quem quiser controlá-lo passa o seu; o
    relógio, quem depende da hora (a tela inicial)."""
    componentes = compor(
        engine,
        bytes(32),
        hasher=HASHER,
        provedor_cep=provedor_cep or ProvedorCepFalso(),
        relogio=relogio,
        pastas=PASTAS,
    )
    return ServicosWeb(
        componentes.autenticacao,
        componentes.sessoes,
        componentes.usuarios,
        componentes.configuracao,
        componentes.autorizacoes,
        componentes.auditoria,
        componentes.integridade,
        componentes.pacientes,
        componentes.contatos,
        componentes.rascunhos,
        componentes.cep,
        componentes.eventos,
        componentes.anulacao,
        componentes.escalas,
        componentes.turnos,
        componentes.frequencia,
        componentes.relatorios,
    )


def montar(
    engine: Engine, provedor_cep: ProvedorCepFalso | None = None, relogio: Relogio | None = None, **config: object
) -> Flask:
    return criar_app(servicos_web(engine, provedor_cep, relogio), ConfigWeb(origem=ORIGEM, **config))  # type: ignore[arg-type]


def get(c: FlaskClient, caminho: str) -> TestResponse:
    return c.get(caminho, base_url=ORIGEM)


def post(c: FlaskClient, caminho: str, dados: dict[str, str], origem: str | None = ORIGEM) -> TestResponse:
    cabecalhos = {"Origin": origem} if origem else {}
    return c.post(caminho, data=dados, base_url=ORIGEM, headers=cabecalhos)


def entrar(c: FlaskClient, login: str, senha: str = SENHA) -> TestResponse:
    return post(c, "/entrar", {"login": login, "senha": senha})


def logado(app: Flask, login: str) -> FlaskClient:
    cliente = app.test_client()
    resposta = entrar(cliente, login)
    assert resposta.status_code == 302, resposta.get_data(as_text=True)
    return cliente
