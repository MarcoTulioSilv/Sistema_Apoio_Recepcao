"""Dados institucionais, logotipo e faixas etárias no MySQL, pelo usuário de banco da web (RF-1201, RF-1202,
RF-1206, DD-50)."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy import Engine, text

from sar.composicao import montar_barramento, montar_executor
from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.modulo_06_configuracao.contrato import DadosInstitucionais
from sar.modulo_06_configuracao.servicos import ServicoConfiguracao, ServicoReferencias
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada

pytestmark = pytest.mark.integracao

AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
JATAI = "5211909"
DADOS = DadosInstitucionais("Clínica Fictícia", "Rua das Flores, 100", "75803000", JATAI, "6436000000", None)


@pytest.fixture
def sem_instituicao(usuarios: dict[str, int], engine_migracao: Engine) -> Iterator[dict[str, int]]:
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM instituicao"))
    yield usuarios
    with engine_migracao.begin() as c:
        c.execute(text("DELETE FROM instituicao"))


def montar(engine: Engine) -> ServicoConfiguracao:
    return ServicoConfiguracao(montar_executor(engine, montar_barramento(RelogioSistema())), ServicoAuditoria())


def pessoa(usuarios: dict[str, int], chave: str, perfil: Perfil) -> Contexto:
    return Contexto(usuarios[chave], perfil, None, "10.0.0.9", AGORA, "e" * 32)


def auditorias(engine: Engine, operacao: str) -> list[dict[str, list[object]]]:
    sql = "SELECT alteracoes FROM auditoria WHERE operacao = :o ORDER BY id"
    with engine.connect() as c:
        return [json.loads(linha[0]) for linha in c.execute(text(sql), {"o": operacao})]


def png(cor: str) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (80, 40), cor).save(saida, format="PNG")
    return saida.getvalue()


@pytest.mark.requisito("RF-1201", "RNF-605", "DD-10")
def test_administracao_informa_e_altera_so_o_que_mudou(sem_instituicao: dict[str, int], engine_web: Engine) -> None:
    servico = montar(engine_web)
    admin = pessoa(sem_instituicao, "admin", Perfil.ADMINISTRACAO)
    assert servico.ver_institucional(admin) is None
    servico.alterar_institucional(admin, DADOS)
    servico.alterar_institucional(admin, DADOS)  # igual: nada gravado nem auditado
    servico.alterar_institucional(admin, replace(DADOS, telefone="(64) 3600-1111", cnpj="11222333000181"))
    vigente = servico.ver_institucional(admin)
    assert vigente is not None
    assert (vigente.municipio.nome, vigente.municipio.uf, vigente.telefone, vigente.cnpj) == (
        "Jataí", "GO", "6436001111", "11222333000181"
    )  # fmt: skip
    registros = auditorias(engine_web, "config.institucional.alterar")
    assert len(registros) == 2 and registros[0]["uf"] == [None, "GO"]
    assert registros[1] == {"telefone": ["6436000000", "6436001111"], "cnpj": [None, "11222333000181"]}


@pytest.mark.requisito("RF-1201")
def test_municipio_inexistente_e_recusado(sem_instituicao: dict[str, int], engine_web: Engine) -> None:
    servico = montar(engine_web)
    admin = pessoa(sem_instituicao, "admin", Perfil.ADMINISTRACAO)
    with pytest.raises(RegraViolada) as erro:
        servico.alterar_institucional(admin, DadosInstitucionais("Clínica", "Rua A, 1", "75803000", "9999999", None,
                                                                 None))  # fmt: skip
    assert erro.value.codigo == "instituicao.municipio"


@pytest.mark.requisito("RF-1201", "RF-1202")
@pytest.mark.parametrize(("chave", "perfil"), [("recepcao", Perfil.RECEPCAO), ("ti", Perfil.TI)])
def test_so_a_administracao_altera(
    sem_instituicao: dict[str, int], engine_web: Engine, chave: str, perfil: Perfil
) -> None:
    servico = montar(engine_web)
    outro = pessoa(sem_instituicao, chave, perfil)
    with pytest.raises(AcessoNegado):
        servico.alterar_institucional(outro, DADOS)
    with pytest.raises(AcessoNegado):
        servico.enviar_logotipo(outro, png("navy"))


@pytest.mark.requisito("RF-1202", "DD-50")
def test_logotipo_reencodado_e_auditado_pelo_hash(sem_instituicao: dict[str, int], engine_web: Engine) -> None:
    servico, leitura = montar(engine_web), ServicoReferencias()
    admin = pessoa(sem_instituicao, "admin", Perfil.ADMINISTRACAO)
    with pytest.raises(RegraViolada) as erro:
        servico.enviar_logotipo(admin, png("navy"))
    assert erro.value.codigo == "instituicao.ausente"
    servico.alterar_institucional(admin, DADOS)
    servico.enviar_logotipo(admin, png("navy"))
    primeiro = servico.logotipo(admin)
    servico.enviar_logotipo(admin, png("navy"))  # mesmo resultado: nada muda
    servico.enviar_logotipo(admin, png("teal"))
    assert primeiro is not None and Image.open(io.BytesIO(primeiro)).format == "PNG"
    registros = auditorias(engine_web, "config.logotipo.enviar")
    assert registros[0] == {"logotipo_sha256": [None, hashlib.sha256(primeiro).hexdigest()]}
    assert len(registros) == 2
    executar = montar_executor(engine_web, montar_barramento(RelogioSistema()))
    vigente = executar(leitura.institucional)
    assert vigente is not None and vigente.tem_logotipo
    assert executar(leitura.logotipo) != primeiro


@pytest.mark.requisito("RF-1206")
def test_onze_faixas_etarias_em_ordem(engine_web: Engine) -> None:
    executar = montar_executor(engine_web, montar_barramento(RelogioSistema()))
    faixas = executar(ServicoReferencias().faixas_etarias)
    assert [(f.inicio, f.fim) for f in faixas] == [(i, i + 9) for i in range(0, 100, 10)] + [(100, None)]
