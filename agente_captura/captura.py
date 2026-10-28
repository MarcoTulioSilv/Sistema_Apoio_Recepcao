"""Uma captura (§8.5, passos 4 a 6): digitaliza, converte e envia página a página; a seguinte é digitalizada enquanto a
anterior viaja. Só conclui a ingestão se todas as páginas chegaram: falha no meio interrompe sem concluir, e a
ingestão expira sozinha no servidor (nenhuma página faltando em silêncio, CT-DOC-14)."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from agente_captura.conversao import PaginaInvalida, bmp_para_png
from agente_captura.envio import Enviador, FalhaDeRede, ServidorRecusou
from agente_captura.scanner import Papel, Scanner, ScannerIndisponivel, SemPapel

FIM = None


class CapturaFalhou(Exception):
    """Desfecho que a tela mostra; `status` vai na resposta ao navegador."""

    def __init__(self, status: int, mensagem: str, motivo: str) -> None:
        super().__init__(motivo)
        self.status = status
        self.mensagem = mensagem  # para a recepcionista (§8.5)
        self.motivo = motivo  # para o registro da estação, sem dado nenhum


SEM_PAPEL = CapturaFalhou(422, "Coloque as folhas no alimentador.", "sem_papel")
INDISPONIVEL = CapturaFalhou(503, "Scanner indisponível. Confira se está ligado e livre.", "scanner_indisponivel")
REDE = CapturaFalhou(502, "A conexão com o servidor falhou. Recomece a digitalização.", "rede")
EXPIRADA = CapturaFalhou(403, "A digitalização expirou ou foi cancelada. Recomece pela tela.", "token")
RECUSADA = CapturaFalhou(422, "O servidor recusou a página. Recomece a digitalização.", "recusada")
ILEGIVEL = CapturaFalhou(502, "O scanner devolveu uma página ilegível. Recomece a digitalização.", "pagina_invalida")


@dataclass(frozen=True, slots=True)
class Resumo:
    paginas: int
    segundos: float


def _falha_do_servidor(erro: ServidorRecusou) -> CapturaFalhou:
    return EXPIRADA if erro.status == 403 else RECUSADA


class Captura:
    def __init__(self, scanner: Scanner, enviador: Enviador) -> None:
        self._scanner = scanner
        self._enviador = enviador

    def executar(self, ingestao: str, token: str, papel: Papel) -> Resumo:
        inicio = time.monotonic()
        fila: queue.Queue[tuple[int, bytes] | None] = queue.Queue(maxsize=2)
        falhas: list[CapturaFalhou] = []

        def enviar() -> None:
            while (item := fila.get()) is not FIM:
                numero, png = item
                if falhas:
                    continue  # já falhou: só esvazia a fila
                try:
                    self._enviador.enviar_pagina(ingestao, token, numero, png)
                except FalhaDeRede:
                    falhas.append(REDE)
                except ServidorRecusou as erro:
                    falhas.append(_falha_do_servidor(erro))

        envio = threading.Thread(target=enviar, name="envio", daemon=True)
        envio.start()
        lidas = 0
        try:
            for bmp in self._scanner.paginas(papel):
                if falhas:
                    break  # o envio falhou: para de digitalizar
                lidas += 1
                fila.put((lidas, bmp_para_png(bmp)))  # o BMP só existe aqui, em memória (SEG-28)
        except SemPapel:
            falhas.append(SEM_PAPEL)
        except ScannerIndisponivel:
            falhas.append(INDISPONIVEL)
        except PaginaInvalida:
            falhas.append(ILEGIVEL)
        finally:
            fila.put(FIM)
            envio.join()
        if falhas:
            raise falhas[0]
        if lidas == 0:
            raise SEM_PAPEL
        try:
            self._enviador.concluir(ingestao, token, lidas)
        except FalhaDeRede:
            raise REDE from None
        except ServidorRecusou as erro:
            raise _falha_do_servidor(erro) from None
        return Resumo(lidas, round(time.monotonic() - inicio, 1))
