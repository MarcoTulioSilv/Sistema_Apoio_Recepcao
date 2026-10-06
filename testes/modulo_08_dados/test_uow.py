"""Semântica da unidade de trabalho sobre um SQLite em memória; o comportamento no MySQL fica em
test_uow_integracao.py."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sar.modulo_08_dados.uow import ExecutorSQL, UnidadeDeTrabalhoSQL, e_repetivel
from sar.nucleo.contexto import Contexto
from sar.nucleo.eventos import Barramento, UsuarioInativado
from sar.nucleo.logs import FormatadorJson
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho

CONTEXTO = Contexto.sistema("teste", datetime(2026, 9, 30, 12, 0, tzinfo=UTC))


def registro(entidade_id: str) -> RegistroAuditoria:
    return RegistroAuditoria(CONTEXTO, "teste.gravar", "teste_uow", entidade_id, {"valor": (None, "x")})


@dataclass
class GravadorFalso:
    passos: list[str]
    falhar: bool = False

    def __call__(self, sessao: Session, registros: Sequence[RegistroAuditoria]) -> None:
        linhas = sessao.execute(text("SELECT COUNT(*) FROM teste_uow")).scalar_one()
        self.passos.append(f"auditoria:{len(registros)}:linhas={linhas}")
        if self.falhar:
            raise RuntimeError("auditoria indisponível")


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.execute(text("CREATE TABLE teste_uow (id INTEGER PRIMARY KEY, valor TEXT)"))
    yield engine
    engine.dispose()


def contar(engine: Engine) -> int:
    with engine.connect() as c:
        return int(c.execute(text("SELECT COUNT(*) FROM teste_uow")).scalar_one())


def inserir(uow: UnidadeDeTrabalho, valor: str = "x") -> None:
    cast(UnidadeDeTrabalhoSQL, uow).sessao.execute(text("INSERT INTO teste_uow (valor) VALUES (:v)"), {"v": valor})


Fabrica = Callable[..., UnidadeDeTrabalhoSQL]


@pytest.fixture
def nova(engine: Engine) -> Fabrica:
    def criar(barramento: Barramento | None = None, gravador: GravadorFalso | None = None) -> UnidadeDeTrabalhoSQL:
        return UnidadeDeTrabalhoSQL(engine, barramento or Barramento(), gravador or GravadorFalso([]), {})

    return criar


@pytest.mark.requisito("DDS-3.3")
def test_confirmar_grava_e_sair_sem_confirmar_desfaz(engine: Engine, nova: Fabrica) -> None:
    with nova() as uow:
        inserir(uow)
    assert contar(engine) == 0
    with nova() as uow:
        inserir(uow)
        uow.confirmar()
    assert contar(engine) == 1


@pytest.mark.requisito("DD-15", "DD-03")
def test_ordem_eventos_auditoria_commit_depois(engine: Engine, nova: Fabrica) -> None:
    passos: list[str] = []
    barramento = Barramento()

    def ao_inativar(uow: UnidadeDeTrabalho, evento: UsuarioInativado) -> None:
        passos.append("evento")
        inserir(uow, "do manipulador")
        uow.auditar(registro("manipulador"))

    barramento.assinar(UsuarioInativado, ao_inativar)
    with nova(barramento, GravadorFalso(passos)) as uow:
        inserir(uow)
        uow.auditar(registro("1"))
        uow.publicar(UsuarioInativado(usuario_id=1))
        uow.depois_do_commit(lambda: passos.append(f"depois:linhas={contar(engine)}"))
        uow.confirmar()

    # A auditoria vê as escritas do manipulador e inclui o registro dele; a ação de depois vê o commit.
    assert passos == ["evento", "auditoria:2:linhas=2", "depois:linhas=2"]


@pytest.mark.requisito("DD-15")
def test_evento_publicado_por_manipulador_tambem_e_despachado(nova: Fabrica) -> None:
    vistos: list[int] = []
    barramento = Barramento()

    def encadeia(uow: UnidadeDeTrabalho, evento: UsuarioInativado) -> None:
        vistos.append(evento.usuario_id)
        if evento.usuario_id == 1:
            uow.publicar(UsuarioInativado(usuario_id=2))

    barramento.assinar(UsuarioInativado, encadeia)
    with nova(barramento) as uow:
        uow.publicar(UsuarioInativado(usuario_id=1))
        uow.confirmar()
    assert vistos == [1, 2]


@pytest.mark.requisito("DD-15")
def test_falha_no_manipulador_desfaz_a_operacao(engine: Engine, nova: Fabrica) -> None:
    passos: list[str] = []
    barramento = Barramento()

    def falha(_uow: UnidadeDeTrabalho, _e: UsuarioInativado) -> None:
        raise RuntimeError("manipulador falhou")

    barramento.assinar(UsuarioInativado, falha)
    with pytest.raises(RuntimeError), nova(barramento, GravadorFalso(passos)) as uow:
        inserir(uow)
        uow.auditar(registro("1"))
        uow.publicar(UsuarioInativado(usuario_id=1))
        uow.depois_do_commit(lambda: passos.append("depois"))
        uow.confirmar()
    assert contar(engine) == 0
    assert passos == []


@pytest.mark.requisito("DD-03")
def test_falha_na_auditoria_desfaz_a_operacao(engine: Engine, nova: Fabrica) -> None:
    passos: list[str] = []
    with pytest.raises(RuntimeError, match="auditoria"), nova(gravador=GravadorFalso(passos, falhar=True)) as uow:
        inserir(uow)
        uow.auditar(registro("1"))
        uow.depois_do_commit(lambda: passos.append("depois"))
        uow.confirmar()
    assert contar(engine) == 0
    assert "depois" not in passos


@pytest.mark.requisito("DD-03")
def test_sem_registro_de_auditoria_o_gravador_nao_e_chamado(nova: Fabrica) -> None:
    passos: list[str] = []
    with nova(gravador=GravadorFalso(passos)) as uow:
        uow.confirmar()
    assert passos == []


@pytest.mark.requisito("DD-59")
def test_acao_de_depois_do_commit_nao_roda_no_rollback(nova: Fabrica) -> None:
    passos: list[str] = []
    with nova() as uow:
        uow.depois_do_commit(lambda: passos.append("depois"))
    assert passos == []


@pytest.mark.requisito("RNF-624", "DD-81")
def test_falha_depois_do_commit_nao_desfaz_e_nao_loga_dado_pessoal(
    engine: Engine, nova: Fabrica, caplog: pytest.LogCaptureFixture
) -> None:
    def falha() -> None:
        raise ValueError("Maria Fictício, CPF 52998224725")

    with caplog.at_level(logging.ERROR), nova() as uow:
        inserir(uow)
        uow.depois_do_commit(falha)
        uow.confirmar()
    assert contar(engine) == 1
    linha = FormatadorJson("teste").format(caplog.records[-1])
    assert json.loads(linha)["evento"] == "uow.depois_do_commit.falhou"
    assert json.loads(linha)["erro"] == "ValueError"
    assert "Maria" not in linha + caplog.text
    assert "52998224725" not in linha + caplog.text


@pytest.mark.requisito("DDS-3.3")
def test_uso_fora_do_bloco_ou_depois_de_confirmar_e_recusado(nova: Fabrica) -> None:
    uow = nova()
    with pytest.raises(RuntimeError):
        uow.auditar(registro("1"))
    with uow:
        uow.confirmar()
        with pytest.raises(RuntimeError):
            uow.confirmar()
        with pytest.raises(RuntimeError):
            uow.publicar(UsuarioInativado(usuario_id=1))
    with pytest.raises(RuntimeError), uow:
        pass


@pytest.mark.requisito("DDS-3.3")
def test_repositorio_e_criado_uma_vez_por_unidade(engine: Engine) -> None:
    class RepositorioTeste:
        def __init__(self, sessao: Session) -> None:
            self.sessao = sessao

    uow = UnidadeDeTrabalhoSQL(engine, Barramento(), GravadorFalso([]), {RepositorioTeste: RepositorioTeste})
    with uow:
        repo = uow.repositorio(RepositorioTeste)
        assert repo is uow.repositorio(RepositorioTeste)
        assert repo.sessao is uow.sessao
        with pytest.raises(LookupError):
            uow.repositorio(str)


# ------------------------------------------------------------------ executor e repetição (DD-59)
class ErroDriver(Exception):
    pass


def erro_banco(codigo: int) -> OperationalError:
    return OperationalError("UPDATE ...", {}, ErroDriver(codigo, "mensagem do driver"))


@pytest.mark.requisito("DD-59")
@pytest.mark.parametrize(("codigo", "repete"), [(1213, True), (1205, True), (1062, False), (2013, False)])
def test_so_impasse_e_trava_esgotada_sao_repetiveis(codigo: int, repete: bool) -> None:
    assert e_repetivel(erro_banco(codigo)) is repete


@pytest.mark.requisito("DD-59")
def test_executor_confirma_e_devolve_o_resultado(engine: Engine, nova: Fabrica) -> None:
    def operacao(uow: UnidadeDeTrabalho) -> str:
        inserir(uow)
        return "feito"

    assert ExecutorSQL(nova)(operacao) == "feito"
    assert contar(engine) == 1


@pytest.mark.requisito("DD-59")
def test_executor_repete_a_operacao_inteira_em_impasse(engine: Engine, nova: Fabrica) -> None:
    tentativas: list[int] = []
    passos: list[str] = []

    def operacao(uow: UnidadeDeTrabalho) -> None:
        tentativas.append(1)
        inserir(uow)
        uow.depois_do_commit(lambda: passos.append(f"depois {len(tentativas)}"))
        if len(tentativas) < 3:
            raise erro_banco(1213)

    ExecutorSQL(nova)(operacao)
    assert len(tentativas) == 3
    assert contar(engine) == 1  # as tentativas desfeitas não deixam rastro
    assert passos == ["depois 3"]


@pytest.mark.requisito("DD-59")
def test_executor_desiste_depois_de_tres_tentativas(engine: Engine, nova: Fabrica) -> None:
    tentativas: list[int] = []

    def operacao(uow: UnidadeDeTrabalho) -> None:
        tentativas.append(1)
        inserir(uow)
        raise erro_banco(1205)

    with pytest.raises(OperationalError):
        ExecutorSQL(nova)(operacao)
    assert len(tentativas) == 3
    assert contar(engine) == 0


@pytest.mark.requisito("DD-59")
def test_executor_nao_repete_erro_que_nao_e_impasse(nova: Fabrica) -> None:
    tentativas: list[int] = []

    def operacao(_uow: UnidadeDeTrabalho) -> None:
        tentativas.append(1)
        raise erro_banco(1062)

    with pytest.raises(OperationalError):
        ExecutorSQL(nova)(operacao)
    assert len(tentativas) == 1
