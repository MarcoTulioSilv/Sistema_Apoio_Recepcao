"""Envio ao servidor do SAR (§8.5, DD-80, DD-94): HTTPS confiando só no certificado raiz da clínica (fixado),
autenticado pelo token de uso único da ingestão. Falha de rede numa página repete a mesma página até 3 vezes; recusa
do servidor (token vencido, arquivo recusado) não se repete."""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

TENTATIVAS = 3
TEMPO = 30.0
PAUSAS = (1.0, 2.0)  # entre as tentativas


class FalhaDeRede(Exception):
    """O servidor não respondeu depois das tentativas."""


class ServidorRecusou(Exception):
    def __init__(self, status: int, codigo: str) -> None:
        super().__init__(f"{status} {codigo}")
        self.status = status
        self.codigo = codigo


def contexto_tls(certificado_raiz: Path) -> ssl.SSLContext:
    """Só a autoridade interna da clínica; o repositório de certificados do Windows não conta (certificado fixado)."""
    contexto = ssl.create_default_context(cafile=str(certificado_raiz))
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    return contexto


class Enviador:
    def __init__(
        self, servidor: str, contexto: ssl.SSLContext | None, pausar: Callable[[float], None] = time.sleep
    ) -> None:
        """Sem contexto TLS, só em desenvolvimento, com servidor HTTP (DD-100)."""
        self._servidor = servidor.rstrip("/")
        self._contexto = contexto
        self._pausar = pausar

    def _pedido(self, metodo: str, caminho: str, token: str, corpo: bytes, tipo: str) -> None:
        url = f"{self._servidor}{caminho}"
        cabecalhos = {"Authorization": f"Bearer {token}", "Content-Type": tipo}
        for tentativa in range(TENTATIVAS):
            pedido = urllib.request.Request(url, data=corpo, method=metodo, headers=cabecalhos)  # noqa: S310
            try:
                with urllib.request.urlopen(pedido, timeout=TEMPO, context=self._contexto):  # noqa: S310 # nosec B310
                    return
            except urllib.error.HTTPError as erro:
                with erro:  # a resposta de erro também segura a conexão
                    if erro.code < 500:
                        try:
                            codigo = str(json.loads(erro.read() or b"{}").get("erro", ""))
                        except ValueError:
                            codigo = ""
                        raise ServidorRecusou(erro.code, codigo) from None
            except urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError:
                pass
            if tentativa < TENTATIVAS - 1:
                self._pausar(PAUSAS[min(tentativa, len(PAUSAS) - 1)])
        raise FalhaDeRede()

    def enviar_pagina(self, ingestao: str, token: str, numero: int, png: bytes) -> None:
        self._pedido("PUT", f"/captura/ingestoes/{ingestao}/paginas/{numero}", token, png, "image/png")

    def concluir(self, ingestao: str, token: str, paginas: int) -> None:
        corpo = json.dumps({"paginas": paginas}).encode()
        self._pedido("POST", f"/captura/ingestoes/{ingestao}/concluir", token, corpo, "application/json")
