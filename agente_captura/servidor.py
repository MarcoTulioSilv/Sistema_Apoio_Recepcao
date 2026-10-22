"""Servidor local do agente (§8.5, DD-39, DD-98): só no loopback, uma rota de trabalho, `POST /capturar`.

- `Origin` diferente da origem configurada: 403, sem acionar o scanner. CORS só para essa origem.
- Uma captura por vez: chamada durante outra recebe 409.
- Responde à verificação de acesso à rede local do Chrome (`Access-Control-Allow-Private-Network`), para quando o
  navegador passar a exigi-la.
- O corpo traz só a ingestão, o token e onde está o papel; o servidor de destino vem da configuração, nunca da
  requisição. Nada de dado de paciente passa por aqui.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agente_captura.captura import CapturaFalhou, Resumo
from agente_captura.scanner import Papel

log = logging.getLogger("agente")

INGESTAO = re.compile(r"^[0-9a-f]{32}$")
TAMANHO_MAXIMO_PEDIDO = 4096
Executar = Callable[[str, str, Papel], Resumo]


class ServidorAgente(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, porta: int, origem: str, executar: Executar) -> None:
        super().__init__(("127.0.0.1", porta), Tratador)
        self.origem = origem.rstrip("/")
        self.executar = executar
        self.ocupado = threading.Lock()


class Tratador(BaseHTTPRequestHandler):
    server: ServidorAgente
    server_version = "SAR-agente"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass  # o registro é o da captura, só com metadados

    def _origem_permitida(self) -> bool:
        return self.headers.get("Origin", "").rstrip("/") == self.server.origem

    def _responder(self, status: int, corpo: dict[str, object] | None = None, cors: bool = True) -> None:
        dados = json.dumps(corpo).encode() if corpo is not None else b""
        self.send_response(status)
        if cors:
            self.send_header("Access-Control-Allow-Origin", self.server.origem)
            self.send_header("Vary", "Origin")
        if corpo is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if dados:
            self.wfile.write(dados)

    def do_OPTIONS(self) -> None:
        """Pré-verificação de CORS e de acesso à rede local."""
        if self.path != "/capturar" or not self._origem_permitida():
            self._responder(403, cors=False)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.server.origem)
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        self._responder(404, {"mensagem": "Não encontrado."}, cors=False)

    def _corpo(self) -> bytes | None:
        """Lê o corpo inteiro, até o limite, antes de qualquer resposta: corpo deixado no socket faz o Windows
        derrubar a conexão, e o navegador veria falha de rede no lugar da recusa. Grande demais: fecha."""
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            tamanho = -1
        if not 0 <= tamanho <= TAMANHO_MAXIMO_PEDIDO:
            self.close_connection = True
            return None
        return self.rfile.read(tamanho)

    def do_POST(self) -> None:
        corpo = self._corpo()
        if self.path != "/capturar":
            self._responder(404, {"mensagem": "Não encontrado."}, cors=False)
            return
        if not self._origem_permitida():
            log.warning("captura.origem_recusada")
            self._responder(403, {"mensagem": "Origem não permitida."}, cors=False)
            return
        pedido = self._ler_pedido(corpo)
        if pedido is None:
            self._responder(400, {"mensagem": "Pedido inválido."})
            return
        if not self.server.ocupado.acquire(blocking=False):
            self._responder(409, {"mensagem": "Já há uma digitalização em andamento nesta estação."})
            return
        try:
            resumo = self.server.executar(*pedido)
        except CapturaFalhou as falha:
            log.warning("captura.falhou", extra={"motivo": falha.motivo})
            self._responder(falha.status, {"mensagem": falha.mensagem})
            return
        except Exception as erro:
            log.error("captura.erro_inesperado", extra={"motivo": type(erro).__name__})
            self._responder(500, {"mensagem": "Erro no programa de digitalização. Chame o TI."})
            return
        finally:
            self.server.ocupado.release()
        log.info("captura.concluida", extra={"paginas": resumo.paginas, "segundos": resumo.segundos})
        self._responder(200, {"paginas": resumo.paginas, "segundos": resumo.segundos})

    @staticmethod
    def _ler_pedido(bruto: bytes | None) -> tuple[str, str, Papel] | None:
        if not bruto:
            return None
        try:
            corpo = json.loads(bruto)
        except ValueError:
            return None
        if not isinstance(corpo, dict) or set(corpo) != {"ingestao", "token", "papel"}:
            return None
        ingestao, token, papel = corpo["ingestao"], corpo["token"], corpo["papel"]
        if not (isinstance(ingestao, str) and INGESTAO.match(ingestao) and isinstance(token, str)
                and 0 < len(token) <= 200 and papel in ("vidro", "alimentador")):  # fmt: skip
            return None
        return ingestao, token, papel
