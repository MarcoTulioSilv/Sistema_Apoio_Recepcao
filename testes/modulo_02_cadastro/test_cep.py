"""Cliente de CEP sem internet (AD-23, DD-88, RNF-612, QAS-03): o transporte do httpx responde no lugar do
ViaCEP e da BrasilAPI."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from sar.modulo_02_cadastro.cep import (
    TEMPO_LIMITE,
    ClienteBrasilApi,
    ClienteViaCep,
    ProvedorCepComReserva,
    novo_cliente,
)
from sar.nucleo.erros import IndisponivelExterno

CEP = "75800000"
VIACEP = {"cep": "75800-000", "logradouro": "", "bairro": "Centro", "localidade": "Jataí", "uf": "GO",
          "ibge": "5211909"}  # fmt: skip
BRASILAPI = {"cep": CEP, "state": "GO", "city": "Jataí", "neighborhood": "Centro", "street": None}

Resposta = Callable[[httpx.Request], httpx.Response]


def provedor(viacep: Resposta, brasilapi: Resposta, pedidos: list[httpx.Request]) -> ProvedorCepComReserva:
    def registrando(resposta: Resposta) -> httpx.MockTransport:
        def tratar(pedido: httpx.Request) -> httpx.Response:
            pedidos.append(pedido)
            return resposta(pedido)

        return httpx.MockTransport(tratar)

    return ProvedorCepComReserva(
        ClienteViaCep(novo_cliente(registrando(viacep))), ClienteBrasilApi(novo_cliente(registrando(brasilapi)))
    )


def json(dados: object, status: int = 200) -> Resposta:
    return lambda _: httpx.Response(status, json=dados)


def fora_do_ar(_: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("tempo esgotado")


@pytest.mark.requisito("RNF-612", "AD-23")
def test_viacep_responde_e_so_o_cep_sai() -> None:
    pedidos: list[httpx.Request] = []
    endereco = provedor(json(VIACEP), fora_do_ar, pedidos).consultar(CEP)
    assert endereco is not None
    assert (endereco.bairro, endereco.municipio_ibge, endereco.uf, endereco.logradouro) == (
        "Centro",
        "5211909",
        "GO",
        None,
    )
    [pedido] = pedidos
    assert (pedido.method, str(pedido.url)) == ("GET", "https://viacep.com.br/ws/75800000/json/")
    assert pedido.content == b"" and not pedido.url.query and "cookie" not in pedido.headers
    assert pedido.headers["user-agent"] == "sar"  # nada que identifique a clínica


@pytest.mark.requisito("DD-88")
def test_cep_inexistente_no_principal_nao_e_reconsultado() -> None:
    pedidos: list[httpx.Request] = []
    assert provedor(json({"erro": "true"}), json(BRASILAPI), pedidos).consultar("75803123") is None
    assert [p.url.host for p in pedidos] == ["viacep.com.br"]  # a BrasilAPI não é consultada


@pytest.mark.requisito("DD-88", "AD-23")
@pytest.mark.parametrize(
    "falha",
    [fora_do_ar, json({}, 500), lambda _: httpx.Response(200, text="<html>"), json([1]),
     lambda _: httpx.Response(301, headers={"Location": "https://outro.example/"})],
    ids=["tempo esgotado", "erro 500", "não é JSON", "JSON sem objeto", "redirecionamento"],
)  # fmt: skip
def test_falha_do_principal_vai_para_a_brasilapi(falha: Resposta) -> None:
    pedidos: list[httpx.Request] = []
    endereco = provedor(falha, json(BRASILAPI), pedidos).consultar(CEP)
    assert endereco is not None
    assert (endereco.municipio_ibge, endereco.municipio_nome, endereco.uf) == (None, "Jataí", "GO")
    assert str(pedidos[-1].url) == "https://brasilapi.com.br/api/cep/v2/75800000"
    assert all(p.url.host in ("viacep.com.br", "brasilapi.com.br") for p in pedidos)  # nunca segue o redirecionamento


@pytest.mark.requisito("QAS-03", "RNF-507")
def test_as_duas_fora_do_ar_e_inexistente_na_reserva() -> None:
    with pytest.raises(IndisponivelExterno):
        provedor(fora_do_ar, json({}, 503), []).consultar(CEP)
    assert provedor(json({}, 500), json({"errors": []}, 404), []).consultar(CEP) is None


@pytest.mark.requisito("RNF-612")
@pytest.mark.parametrize("cep", ["75800-000", "7580000", "75800000 ", "７５８０００００"])
def test_so_cep_de_8_digitos_vai_para_a_url(cep: str) -> None:
    pedidos: list[httpx.Request] = []
    with pytest.raises(ValueError, match="8 dígitos"):
        provedor(json(VIACEP), json(BRASILAPI), pedidos).consultar(cep)
    assert pedidos == []


@pytest.mark.requisito("DD-88")
def test_cliente_com_tempo_limite_curto_e_sem_redirecionamento() -> None:
    cliente = novo_cliente()
    assert cliente.timeout.connect == TEMPO_LIMITE == 3.0 and cliente.timeout.read == TEMPO_LIMITE
    assert not cliente.follow_redirects


def por_cep(respostas: dict[str, object]) -> Resposta:
    """ViaCEP simulado: o JSON de cada CEP conhecido; os outros, "erro": "true"."""

    def tratar(pedido: httpx.Request) -> httpx.Response:
        cep = pedido.url.path.split("/")[2]
        return httpx.Response(200, json=respostas.get(cep, {"erro": "true"}))

    return tratar


@pytest.mark.requisito("DD-88", "AD-23")
def test_cep_geral_da_cidade_traz_o_municipio_pelo_vizinho() -> None:
    """Defeito encontrado em uso: 75800-000, o CEP geral de Jataí, não existe na base dos Correios (a cidade tem
    CEP por logradouro), e o preenchimento não trazia o município."""
    pedidos: list[httpx.Request] = []
    rua = {"cep": "75800-001", "logradouro": "Avenida Fictícia", "bairro": "Setor Central", "localidade": "Jataí",
           "uf": "GO", "ibge": "5211909"}  # fmt: skip
    endereco = provedor(por_cep({"75800001": rua}), json(BRASILAPI), pedidos).consultar("75800000")
    assert endereco is not None
    assert (endereco.cep, endereco.logradouro, endereco.bairro) == ("75800000", None, None)  # só o município
    assert (endereco.municipio_ibge, endereco.uf, endereco.municipio_nome) == ("5211909", "GO", "Jataí")
    assert [str(p.url) for p in pedidos] == [
        "https://viacep.com.br/ws/75800000/json/", "https://viacep.com.br/ws/75800001/json/"
    ]  # fmt: skip


@pytest.mark.requisito("DD-88", "RNF-612")
def test_cep_geral_sem_vizinho_e_cep_comum_inexistente_nao_consultam_mais() -> None:
    pedidos: list[httpx.Request] = []
    assert provedor(por_cep({}), json(BRASILAPI), pedidos).consultar("75803000") is None
    assert len(pedidos) == 2  # o próprio e o vizinho -001, nada além
    pedidos.clear()
    assert provedor(por_cep({}), json(BRASILAPI), pedidos).consultar("75803123") is None
    assert len(pedidos) == 1  # não termina em -000: sem vizinho
