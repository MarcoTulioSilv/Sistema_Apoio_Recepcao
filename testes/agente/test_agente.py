"""Agente de captura com scanner falso e servidor do SAR falso em HTTPS (DDS §8.5): CT-DOC-11 a CT-DOC-14; DD-39,
DD-77, DD-79, DD-80, SEG-28."""

from __future__ import annotations

import http.client
import io
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from agente_captura import configuracao, wia
from agente_captura.captura import Captura
from agente_captura.envio import Enviador, contexto_tls
from agente_captura.servidor import ServidorAgente
from testes.apoio.agente import Certificados, ScannerFalso, ServidorSarFalso, gerar_certificados

ORIGEM = "https://sar.clinica.teste"
INGESTAO = "a" * 32


@dataclass
class Bancada:
    sar: ServidorSarFalso
    scanner: ScannerFalso
    agente: ServidorAgente

    def pedir(self, corpo: dict[str, object] | None = None, origem: str | None = ORIGEM,
              metodo: str = "POST") -> tuple[int, dict[str, object], http.client.HTTPMessage]:  # fmt: skip
        conexao = http.client.HTTPConnection("127.0.0.1", self.agente.server_address[1], timeout=10)
        padrao = {"ingestao": INGESTAO, "token": "token-valido", "papel": "alimentador"}
        dados = json.dumps(corpo if corpo is not None else padrao).encode()
        cabecalhos = {"Content-Type": "application/json"}
        if origem:
            cabecalhos["Origin"] = origem
        conexao.request(metodo, "/capturar", body=dados if metodo == "POST" else None, headers=cabecalhos)
        resposta = conexao.getresponse()
        bruto = resposta.read()
        conexao.close()
        return resposta.status, (json.loads(bruto) if bruto else {}), resposta.headers


def _bancada(certificados: Certificados, raiz: Path | None = None) -> Iterator[Bancada]:
    sar = ServidorSarFalso(certificados).iniciar()
    scanner = ScannerFalso(folhas=3)
    enviador = Enviador(sar.endereco, contexto_tls(raiz or certificados.raiz), pausar=lambda _s: None)
    agente = ServidorAgente(0, ORIGEM, Captura(scanner, enviador).executar)
    threading.Thread(target=agente.serve_forever, daemon=True).start()
    yield Bancada(sar, scanner, agente)
    agente.shutdown()
    agente.server_close()
    sar.shutdown()
    sar.server_close()


@pytest.fixture
def certificados(tmp_path: Path) -> Certificados:
    return gerar_certificados(tmp_path / "certificados")


@pytest.fixture
def bancada(certificados: Certificados) -> Iterator[Bancada]:
    yield from _bancada(certificados)


# ------------------------------------------------------------------ CT-DOC-11
@pytest.mark.requisito("CT-DOC-11", "DD-39")
def test_origem_nao_configurada_recebe_403_sem_acionar_o_scanner(bancada: Bancada) -> None:
    for origem in ("https://outro.site", None, "https://sar.clinica.teste.outro"):
        status, _, cabecalhos = bancada.pedir(origem=origem)
        assert status == 403 and "Access-Control-Allow-Origin" not in cabecalhos, origem
    assert bancada.scanner.chamadas == []
    status, _, _ = bancada.pedir(origem="https://outro.site", metodo="OPTIONS")
    assert status == 403
    status, _, cabecalhos = bancada.pedir(metodo="OPTIONS")  # pré-verificação da origem certa
    assert status == 204 and cabecalhos["Access-Control-Allow-Origin"] == ORIGEM
    assert cabecalhos["Access-Control-Allow-Private-Network"] == "true"


@pytest.mark.requisito("CT-DOC-11", "DD-39")
def test_segunda_captura_simultanea_recebe_409(bancada: Bancada) -> None:
    bancada.scanner.liberar = threading.Event()
    primeira: list[int] = []
    linha = threading.Thread(target=lambda: primeira.append(bancada.pedir()[0]))
    linha.start()
    while not bancada.scanner.chamadas:  # a primeira já está no scanner
        threading.Event().wait(0.01)
    status, corpo, _ = bancada.pedir()
    assert status == 409 and "em andamento" in str(corpo["mensagem"])
    bancada.scanner.liberar.set()
    linha.join(10)
    assert primeira == [200] and bancada.scanner.chamadas == ["alimentador"]


@pytest.mark.requisito("DD-39")
def test_pedido_fora_do_formato_e_recusado(bancada: Bancada) -> None:
    for corpo in ({"ingestao": "x", "token": "t", "papel": "vidro"},
                  {"ingestao": INGESTAO, "token": "t", "papel": "gaveta"},
                  {"ingestao": INGESTAO, "token": "t", "papel": "vidro", "servidor": "https://outro"}):  # fmt: skip
        assert bancada.pedir(corpo)[0] == 400, corpo
    assert bancada.scanner.chamadas == []


# ------------------------------------------------------------------ CT-DOC-12
@pytest.mark.requisito("CT-DOC-12", "DD-77", "DD-78", "SEG-28")
def test_bmp_chega_como_png_e_nada_e_gravado_na_estacao(
    bancada: Bancada, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    estacao = tmp_path / "estacao"
    estacao.mkdir()
    for variavel in ("TEMP", "TMP", "TMPDIR", "LOCALAPPDATA"):
        monkeypatch.setenv(variavel, str(estacao))
    monkeypatch.chdir(estacao)
    status, corpo, _ = bancada.pedir()
    assert status == 200 and corpo["paginas"] == 3
    for numero in (1, 2, 3):
        png = bancada.sar.registro.paginas[numero]
        imagem = Image.open(io.BytesIO(png))
        assert png.startswith(b"\x89PNG") and imagem.mode == "L" and imagem.size == (850, 1100)
    assert list(estacao.rglob("*")) == []  # nenhum arquivo de imagem, nem temporário
    assert ".SaveFile(" not in Path(wia.__file__).read_text(encoding="utf-8")  # o WIA entrega em memória


# ------------------------------------------------------------------ CT-DOC-13
@pytest.mark.requisito("CT-DOC-13")
def test_alimentador_com_n_folhas_gera_n_paginas(bancada: Bancada) -> None:
    bancada.scanner.folhas = 5
    status, corpo, _ = bancada.pedir()
    assert (status, corpo["paginas"]) == (200, 5)
    assert sorted(bancada.sar.registro.paginas) == [1, 2, 3, 4, 5] and bancada.sar.registro.concluidas == [5]
    status, corpo, _ = bancada.pedir({"ingestao": INGESTAO, "token": "token-valido", "papel": "vidro"})
    assert (status, corpo["paginas"]) == (200, 1)  # no vidro, uma folha


@pytest.mark.requisito("CT-DOC-13")
def test_alimentador_vazio_e_scanner_indisponivel(bancada: Bancada) -> None:
    bancada.scanner.folhas = 0
    status, corpo, _ = bancada.pedir()
    assert (status, corpo["mensagem"]) == (422, "Coloque as folhas no alimentador.")
    bancada.scanner.indisponivel = True
    status, corpo, _ = bancada.pedir()
    assert status == 503 and str(corpo["mensagem"]).startswith("Scanner indisponível")
    assert bancada.sar.registro.concluidas == []  # a ingestão continua aberta até expirar


# ------------------------------------------------------------------ CT-DOC-14
@pytest.mark.requisito("CT-DOC-14")
def test_queda_de_rede_repete_a_mesma_pagina(bancada: Bancada) -> None:
    bancada.sar.registro.falhas = {2: 2}  # queda e 503 na página 2; a terceira tentativa passa
    status, corpo, _ = bancada.pedir()
    assert (status, corpo["paginas"]) == (200, 3)
    assert bancada.sar.registro.tentativas[2] == 3 and sorted(bancada.sar.registro.paginas) == [1, 2, 3]
    assert bancada.sar.registro.concluidas == [3]


@pytest.mark.requisito("CT-DOC-14")
def test_tentativas_esgotadas_interrompem_sem_concluir(bancada: Bancada) -> None:
    bancada.scanner.folhas, bancada.scanner.intervalo = 6, 0.2
    bancada.sar.registro.falhas = {2: 3}
    status, corpo, _ = bancada.pedir()
    assert status == 502 and "Recomece" in str(corpo["mensagem"])
    assert bancada.sar.registro.tentativas[2] == 3 and bancada.sar.registro.concluidas == []  # nada em silêncio
    assert bancada.scanner.entregues < 6  # parou de digitalizar


# ------------------------------------------------------------------ servidor: token e certificado fixado
@pytest.mark.requisito("DD-94", "SEG-01")
def test_token_recusado_pelo_servidor_nao_se_repete(bancada: Bancada) -> None:
    bancada.sar.registro.token = "outro"
    status, corpo, _ = bancada.pedir()
    assert status == 403 and "expirou" in str(corpo["mensagem"])
    assert bancada.sar.registro.tentativas == {1: 1}


@pytest.mark.requisito("DD-39", "DD-80")
def test_servidor_com_certificado_de_outra_autoridade_nao_recebe_nada(certificados: Certificados,
                                                                       tmp_path: Path) -> None:  # fmt: skip
    outra = gerar_certificados(tmp_path / "outra", "Autoridade Desconhecida")
    for bancada in _bancada(certificados, raiz=outra.raiz):
        status, _, _ = bancada.pedir()
        assert status == 502 and bancada.sar.registro.paginas == {}


# ------------------------------------------------------------------ configuração e WIA
@pytest.mark.requisito("DD-39", "DD-79", "DD-80", "DD-98", "DD-100")
def test_configuracao_da_estacao(tmp_path: Path, certificados: Certificados) -> None:
    arquivo = tmp_path / "agente.json"
    dados = {"servidor": "https://sar.clinica.teste/", "certificado_raiz": str(certificados.raiz),
             "scanner": "Brother DCP-L2540DW"}  # fmt: skip
    arquivo.write_text(json.dumps(dados), encoding="utf-8")
    config = configuracao.carregar(arquivo)
    assert (config.servidor, config.porta, config.origem_permitida) == (ORIGEM, 47830, ORIGEM)
    for errado, mensagem in (({"servidor": "http://sar.clinica.teste"}, "https"),
                             ({"servidor": "https://sar/caminho"}, "sem caminho"),
                             ({"scanner": " "}, "nome do scanner"), ({"porta": "80"}, "porta"),
                             ({"certificado_raiz": str(tmp_path / "nao.crt")}, "certificado")):  # fmt: skip
        with pytest.raises(configuracao.ConfiguracaoInvalida, match=mensagem):
            configuracao.de_dicionario({**dados, **errado})
    with pytest.raises(configuracao.ConfiguracaoInvalida, match="não encontrada"):
        configuracao.carregar(tmp_path / "outro.json")
    # DD-100: HTTP, sem certificado, só com a chave de desenvolvimento.
    homologacao = {"servidor": "http://192.168.0.10:8080", "scanner": "Brother DCP-L2540DW", "desenvolvimento": True}
    assert configuracao.de_dicionario(homologacao).servidor == "http://192.168.0.10:8080"
    with pytest.raises(configuracao.ConfiguracaoInvalida, match="https"):
        configuracao.de_dicionario({**homologacao, "desenvolvimento": False})
    with pytest.raises(configuracao.ConfiguracaoInvalida, match="https"):
        configuracao.de_dicionario({**homologacao, "desenvolvimento": "sim"})  # só o valor true liga


def test_codigo_de_erro_do_wia() -> None:
    sem_papel = Exception(-2147352567, "Exceção.", (0, None, None, None, 0, -2145320957), None)
    assert wia.hresult(sem_papel) == wia.SEM_PAPEL  # pelo IDispatch, o código vem no excepinfo
    assert wia.hresult(Exception(-2145320957, "x", None, None)) == wia.SEM_PAPEL
    assert wia.hresult(Exception("sem código")) == 0
