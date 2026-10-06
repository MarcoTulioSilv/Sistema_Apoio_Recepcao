from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator

import pytest

from sar.nucleo.logs import (
    ATRIBUTO_RESTRICAO,
    CAMPOS,
    EVENTO_DESCARTADO,
    VALOR_DESCARTADO,
    FormatadorJson,
    encerrar_requisicao,
    identificar_usuario,
    iniciar_requisicao,
)
from testes.apoio.fabrica import VALORES_SENSIVEIS, Fabrica
from testes.apoio.vazamento import vazamentos

FORMATADOR = FormatadorJson("teste")


@pytest.fixture(autouse=True)
def sem_requisicao() -> Iterator[None]:
    encerrar_requisicao()
    yield
    encerrar_requisicao()


def registro(
    msg: str, *args: object, extra: dict[str, object] | None = None, erro: BaseException | None = None
) -> dict:
    exc_info = (type(erro), erro, erro.__traceback__) if erro else None
    rec = logging.LogRecord("sar.teste", logging.ERROR, __file__, 1, msg, args or None, exc_info)
    for campo, valor in (extra or {}).items():
        setattr(rec, campo, valor)
    linha = FORMATADOR.format(rec)
    assert "\n" not in linha
    return dict(json.loads(linha))


@pytest.mark.requisito("RNF-624", "DD-81")
def test_linha_tem_so_campos_da_lista_permitida() -> None:
    dados = registro("teste.evento", extra={"resultado": "ok", "duracao_ms": 12.34, "cpf": "52998224725"})
    assert set(dados) <= set(CAMPOS)
    assert dados["evento"] == "teste.evento"
    assert dados["modulo"] == "sar.teste"
    assert dados["duracao_ms"] == 12.3
    assert dados["instante"].endswith("Z")
    assert "cpf" not in dados


@pytest.mark.requisito("RNF-624", "DD-81")
@pytest.mark.parametrize("msg", ["Paciente %s não encontrado", "texto livre de biblioteca", "Maria Fictício"])
def test_mensagem_que_nao_e_codigo_de_evento_e_descartada(msg: str) -> None:
    dados = registro(msg, "Maria Fictício") if "%s" in msg else registro(msg)
    assert dados["evento"] == EVENTO_DESCARTADO
    assert "Maria" not in json.dumps(dados)


@pytest.mark.requisito("RNF-624", "DD-81")
def test_valor_livre_em_campo_de_codigo_e_descartado() -> None:
    dados = registro("teste.evento", extra={"resultado": "CPF 529.982.247-25", "perfil": "recepcao"})
    assert dados["resultado"] == VALOR_DESCARTADO
    assert dados["perfil"] == "recepcao"


@pytest.mark.requisito("RNF-624", "DD-81")
def test_excecao_vira_tipo_e_restricao_sem_mensagem() -> None:
    erro = ValueError("Duplicate entry '52998224725' for key 'paciente.uq_paciente__cpf'")
    setattr(erro, ATRIBUTO_RESTRICAO, "uq_paciente__cpf")
    dados = registro("teste.falhou", erro=erro)
    assert dados["erro"] == "ValueError"
    assert dados["restricao"] == "uq_paciente__cpf"
    assert "52998224725" not in json.dumps(dados)


@pytest.mark.requisito("DD-81", "CT-LOG-04")
def test_requisicao_e_usuario_vem_do_contexto_da_requisicao() -> None:
    ident = iniciar_requisicao()
    identificar_usuario(7, "recepcao")
    dados = registro("teste.evento")
    assert len(ident) == 32
    assert (dados["requisicao_id"], dados["usuario_id"], dados["perfil"]) == (ident, 7, "recepcao")
    encerrar_requisicao()
    assert "requisicao_id" not in registro("teste.evento")


@pytest.mark.requisito("DD-81")
def test_id_de_requisicao_recebido_fora_do_formato_e_substituido() -> None:
    assert iniciar_requisicao("a" * 32) == "a" * 32
    novo = iniciar_requisicao("<script>")
    assert novo != "<script>" and len(novo) == 32


@pytest.mark.requisito("RNF-624", "CT-LOG-01")
def test_formatador_nao_deixa_passar_dado_gerado_pela_fabrica(fabrica: Fabrica) -> None:
    p = fabrica.paciente()
    linhas = [
        FORMATADOR.format(logging.LogRecord("x", logging.ERROR, __file__, 1, p.nome, None, None)),
        FORMATADOR.format(logging.LogRecord("x", logging.ERROR, __file__, 1, "evento %s", (p.cpf,), None)),
        FORMATADOR.format(logging.LogRecord("x", logging.ERROR, __file__, 1, "a.b", None, sys.exc_info())),
    ]
    assert vazamentos(linhas, VALORES_SENSIVEIS) == []


@pytest.mark.requisito("CT-LOG-01")
def test_detector_aponta_a_linha_com_o_valor() -> None:
    assert vazamentos(['{"evento":"a.b"}', '{"resultado":"52998224725"}'], {"52998224725"}) == [
        '{"resultado":"52998224725"}'
    ]


@pytest.mark.requisito("DD-81")
def test_configurar_liga_o_json_na_raiz_e_carimba_o_contexto(capsys: pytest.CaptureFixture[str]) -> None:
    from sar.nucleo.logs import configurar

    raiz = logging.getLogger()
    handlers, nivel, fabrica_registro = list(raiz.handlers), raiz.level, logging.getLogRecordFactory()
    try:
        configurar("teste")
        ident = iniciar_requisicao()
        logging.getLogger("sar.x").info("teste.evento")
        logging.getLogger("sqlalchemy.engine").info("SELECT nome FROM paciente WHERE cpf = '52998224725'")
        encerrar_requisicao()
    finally:
        for handler in list(raiz.handlers):
            raiz.removeHandler(handler)
        for handler in handlers:
            raiz.addHandler(handler)
        raiz.setLevel(nivel)
        logging.setLogRecordFactory(fabrica_registro)
        logging.captureWarnings(False)
    linhas = capsys.readouterr().err.splitlines()
    assert [json.loads(linha)["evento"] for linha in linhas] == ["teste.evento"]  # o SQL nem chega a ser escrito
    assert json.loads(linhas[0])["requisicao_id"] == ident
