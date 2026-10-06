"""Cadeia da trilha no MySQL: CT-AUD-01 (ida e volta), CT-AUD-02 (concorrência) e CT-AUD-04 (privilégios)."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_08_dados.cadeia import gravar_encadeado, json_da_linha
from sar.modulo_08_dados.canonico import HASH_INICIAL, calcular_hash
from sar.modulo_08_dados.modelos.acesso import Auditoria, AuditoriaCabeca
from sar.modulo_08_dados.uow import ExecutorSQL, UnidadeDeTrabalhoSQL
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.eventos import Barramento
from sar.nucleo.uow import UnidadeDeTrabalho
from testes.conftest import ZERAR_TRILHA

pytestmark = pytest.mark.integracao

INSTANTE = datetime(2026, 9, 30, 12, 15, 0, 654321, tzinfo=UTC)
AUDITORIA = ServicoAuditoria()


def executor(engine: Engine) -> ExecutorSQL:
    return ExecutorSQL(lambda: UnidadeDeTrabalhoSQL(engine, Barramento(), gravar_encadeado, {}))


def linhas(engine: Engine) -> list[Auditoria]:
    with Session(engine) as s:
        return list(s.scalars(select(Auditoria).order_by(Auditoria.id)))


def cabeca(engine: Engine) -> tuple[int, str]:
    with Session(engine) as s:
        c = s.get_one(AuditoriaCabeca, 1)
        return c.ultimo_registro_id, c.ultimo_hash


def conferir_cadeia(registros: list[Auditoria]) -> str:
    anterior = HASH_INICIAL
    for linha in registros:
        assert linha.hash_anterior == anterior, f"elo {linha.id} não aponta para o anterior"
        assert calcular_hash(anterior, json_da_linha(linha)) == linha.hash_registro, f"hash do elo {linha.id}"
        anterior = linha.hash_registro
    return anterior


@pytest.fixture
def usuarios(trilha_zerada: Engine) -> Iterator[tuple[int, int, int]]:
    """Recepcionista com sessão e um administrador, para os campos com chave estrangeira."""
    with trilha_zerada.begin() as c:
        for login, perfil in (("teste_cadeia_r", "recepcao"), ("teste_cadeia_a", "administracao")):
            c.execute(
                text(
                    "INSERT INTO usuario (nome, login, senha_hash, perfil, criado_em) "
                    "VALUES ('Usuário de teste', :l, REPEAT('x', 60), :p, NOW(6))"
                ),
                {"l": login, "p": perfil},
            )
        recepcao = c.execute(text("SELECT id FROM usuario WHERE login = 'teste_cadeia_r'")).scalar_one()
        admin = c.execute(text("SELECT id FROM usuario WHERE login = 'teste_cadeia_a'")).scalar_one()
        c.execute(
            text(
                "INSERT INTO sessao_usuario (token_hash, usuario_id, origem, criada_em, ultimo_acesso) "
                "VALUES (REPEAT('d', 64), :u, '10.0.0.5', NOW(6), NOW(6))"
            ),
            {"u": recepcao},
        )
        sessao = c.execute(text("SELECT id FROM sessao_usuario WHERE usuario_id = :u"), {"u": recepcao}).scalar_one()
    yield recepcao, admin, sessao
    with trilha_zerada.begin() as c:
        for comando in ZERAR_TRILHA:  # a trilha aponta para os usuários: sai antes deles
            c.execute(text(comando))
        c.execute(text("DELETE FROM sessao_usuario WHERE id = :s"), {"s": sessao})
        c.execute(text("DELETE FROM usuario WHERE id IN (:r, :a)"), {"r": recepcao, "a": admin})


@pytest.mark.requisito("CT-AUD-01", "DDS-3.10", "DD-71")
def test_ida_e_volta_ao_banco_recalcula_o_mesmo_hash(engine_web: Engine, usuarios: tuple[int, int, int]) -> None:
    recepcao, admin, sessao = usuarios
    contexto = Contexto(recepcao, Perfil.RECEPCAO, sessao, "10.0.0.5", INSTANTE, "b" * 32)
    alteracoes = {
        "nome": ("Conceição Fictício", "Conceição da Silva Fictício"),
        "nascimento": (date(1960, 1, 2), date(1960, 2, 1)),
        "valor": (Decimal("1.10"), Decimal("2.00")),
        "ativo": (True, False),
    }

    def operacao(uow: UnidadeDeTrabalho) -> None:
        AUDITORIA.registrar(uow, contexto, "teste.ida_e_volta", "paciente", "42", alteracoes, "motivo", admin)

    executor(engine_web)(operacao)
    [linha] = linhas(engine_web)
    assert (linha.id, linha.usuario_id, linha.autorizador_id, linha.sessao_id) == (1, recepcao, admin, sessao)
    assert linha.requisicao_id == "b" * 32
    assert linha.instante == INSTANTE.replace(tzinfo=None)  # microssegundos preservados
    assert "Conceição" in (linha.alteracoes or "")  # sem escape de não ASCII
    assert conferir_cadeia([linha]) == cabeca(engine_web)[1]


@pytest.mark.requisito("CT-AUD-02", "DD-03", "DD-71")
def test_cem_operacoes_concorrentes_de_web_e_worker_formam_cadeia_continua(
    trilha_zerada: Engine, engine_web: Engine, engine_worker: Engine
) -> None:
    executores = {"web": executor(engine_web), "worker": executor(engine_worker)}

    def operar(i: int) -> None:
        processo = "web" if i % 2 == 0 else "worker"
        contexto = Contexto.sistema(processo, INSTANTE)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            AUDITORIA.registrar(uow, contexto, "teste.concorrencia", "teste", str(i), {"i": (None, i)})

        executores[processo](operacao)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(operar, range(100)))

    registros = linhas(trilha_zerada)
    assert [linha.id for linha in registros] == list(range(1, 101))  # sem elo repetido nem faltando
    assert sorted(int(linha.entidade_id or "") for linha in registros) == list(range(100))
    assert {linha.origem for linha in registros} == {"web", "worker"}
    assert cabeca(trilha_zerada) == (100, conferir_cadeia(registros))


@pytest.mark.requisito("CT-AUD-04", "RNF-609", "DD-58")
@pytest.mark.parametrize("processo", ["engine_web", "engine_worker"])
@pytest.mark.parametrize(
    "comando",
    [
        "UPDATE auditoria SET motivo = 'adulterado'",
        "DELETE FROM auditoria",
        "UPDATE auditoria_cabeca SET id = 2",
        "DELETE FROM auditoria_cabeca",
    ],
)
def test_usuario_da_aplicacao_nao_altera_nem_apaga_a_trilha(
    request: pytest.FixtureRequest, processo: str, comando: str
) -> None:
    engine: Engine = request.getfixturevalue(processo)
    with pytest.raises((OperationalError, ProgrammingError)) as erro, engine.begin() as c:
        c.execute(text(comando))
    assert erro.value.orig.args[0] in (1142, 1143)  # comando ou coluna negados
