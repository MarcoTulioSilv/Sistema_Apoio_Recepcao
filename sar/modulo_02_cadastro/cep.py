"""Cliente de CEP (AD-23, DD-88): o único código do SAR que acessa a internet. ViaCEP como principal e
BrasilAPI na falha dele; tempo limite curto, só HTTPS, sem seguir redirecionamento, e a requisição leva apenas o
CEP de 8 dígitos no caminho (RNF-612). Indisponibilidade nunca impede o cadastro (QAS-03, RNF-507)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from sar.nucleo.erros import IndisponivelExterno
from sar.nucleo.portas import EnderecoCep, ProvedorCep

log = logging.getLogger(__name__)
TEMPO_LIMITE = 3.0  # segundos por fonte (DD-88)
CABECALHOS = {"Accept": "application/json", "User-Agent": "sar"}  # nada que identifique a clínica ou o paciente


def novo_cliente(transporte: httpx.BaseTransport | None = None) -> httpx.Client:
    """O transporte só muda nos testes, que nunca acessam a internet."""
    return httpx.Client(
        timeout=TEMPO_LIMITE, follow_redirects=False, headers=CABECALHOS, transport=transporte, trust_env=False
    )


def _so_digitos(cep: str) -> str:
    if len(cep) != 8 or not (cep.isascii() and cep.isdigit()):
        raise ValueError("CEP com 8 dígitos")  # quem chama já normalizou; aqui é a última barreira (RNF-612)
    return cep


def _texto(valor: Any) -> str | None:
    return valor.strip() or None if isinstance(valor, str) else None


class _Fonte:
    nome: str

    def __init__(self, cliente: httpx.Client) -> None:
        self._cliente = cliente

    def _get(self, url: str) -> httpx.Response:
        try:
            return self._cliente.get(url)
        except httpx.HTTPError as erro:  # tempo esgotado, conexão recusada, TLS
            raise IndisponivelExterno(self.nome) from erro

    def _json(self, resposta: httpx.Response) -> dict[str, Any]:
        try:
            dados = resposta.json()
        except ValueError:
            raise IndisponivelExterno(self.nome) from None
        if not isinstance(dados, dict):
            raise IndisponivelExterno(self.nome)
        return dados


class ClienteViaCep(_Fonte):
    nome = "viacep"
    BASE = "https://viacep.com.br/ws"

    def consultar(self, cep: str) -> EnderecoCep | None:
        resposta = self._get(f"{self.BASE}/{_so_digitos(cep)}/json/")
        if resposta.status_code != 200:
            raise IndisponivelExterno(self.nome)
        dados = self._json(resposta)
        if dados.get("erro") in (True, "true"):
            return None  # o ViaCEP diz que o CEP não existe
        ibge = _texto(dados.get("ibge"))
        return EnderecoCep(
            cep=cep,
            logradouro=_texto(dados.get("logradouro")),
            bairro=_texto(dados.get("bairro")),
            municipio_ibge=ibge if ibge and len(ibge) == 7 and ibge.isdigit() else None,
            uf=_texto(dados.get("uf")),
            municipio_nome=_texto(dados.get("localidade")),
        )


class ClienteBrasilApi(_Fonte):
    nome = "brasilapi"
    BASE = "https://brasilapi.com.br/api/cep/v2"

    def consultar(self, cep: str) -> EnderecoCep | None:
        resposta = self._get(f"{self.BASE}/{_so_digitos(cep)}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code != 200:
            raise IndisponivelExterno(self.nome)
        dados = self._json(resposta)
        return EnderecoCep(
            cep=cep,
            logradouro=_texto(dados.get("street")),
            bairro=_texto(dados.get("neighborhood")),
            municipio_ibge=None,  # a BrasilAPI não informa; o serviço resolve pelo nome e pela UF
            uf=_texto(dados.get("state")),
            municipio_nome=_texto(dados.get("city")),
        )


class ProvedorCepComReserva:
    """Implementa a porta ProvedorCep (AD-23): o alternativo só quando o principal falha. CEP declarado
    inexistente pelo principal não é reconsultado (DD-88).

    CEP geral: o "CEP da cidade" terminado em -000 (75800-000, Jataí) não existe na base dos Correios quando a
    cidade tem CEP por logradouro. Nesse caso consulta-se o vizinho -001, do mesmo prefixo, e só o município dele
    é aproveitado; logradouro e bairro ficam para a pessoa preencher. Uma consulta a mais, individual (DD-88)."""

    def __init__(self, principal: ProvedorCep, alternativo: ProvedorCep) -> None:
        self._principal = principal
        self._alternativo = alternativo

    def consultar(self, cep: str) -> EnderecoCep | None:
        endereco = self._com_reserva(cep)
        if endereco is not None or not cep.endswith("000"):
            return endereco
        vizinho = self._com_reserva(f"{cep[:5]}001")
        if vizinho is None:
            return None
        log.info("cadastro.cep.geral", extra={"resultado": "municipio_pelo_vizinho"})
        return EnderecoCep(cep, None, None, vizinho.municipio_ibge, vizinho.uf, vizinho.municipio_nome)

    def _com_reserva(self, cep: str) -> EnderecoCep | None:
        try:
            return self._principal.consultar(cep)
        except IndisponivelExterno:
            log.warning("cadastro.cep.principal_indisponivel", extra={"resultado": "alternativo"})
        try:
            return self._alternativo.consultar(cep)
        except IndisponivelExterno:
            log.warning("cadastro.cep.indisponivel", extra={"resultado": "sem_verificacao"})
            raise


def provedor_padrao() -> ProvedorCepComReserva:
    """O que a composição liga: os dois clientes com um httpx.Client cada (a composição não importa o httpx)."""
    return ProvedorCepComReserva(ClienteViaCep(novo_cliente()), ClienteBrasilApi(novo_cliente()))
