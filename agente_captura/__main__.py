"""Ponto de entrada do agente: `python -m agente_captura` ou o executável `sar-agente.exe` (PyInstaller).

Lê a configuração da estação, liga o servidor no loopback e fica até o Windows encerrar a sessão. O registro vai para
%LOCALAPPDATA%\\SAR\\agente.log, com rotação, só com metadados: data, páginas, tempos e resultado, nunca imagem nem
dado de paciente (§8.5).
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from agente_captura import configuracao
from agente_captura.captura import Captura
from agente_captura.envio import Enviador, contexto_tls
from agente_captura.servidor import ServidorAgente


class FormatoRegistro(logging.Formatter):
    """Uma linha por evento, com os campos de metadado que houver; nunca a mensagem de uma exceção."""

    CAMPOS = ("motivo", "paginas", "segundos")

    def format(self, registro: logging.LogRecord) -> str:
        extras = " ".join(f"{c}={getattr(registro, c)}" for c in self.CAMPOS if hasattr(registro, c))
        return f"{self.formatTime(registro)} {registro.levelname} {registro.getMessage()} {extras}".rstrip()


def configurar_registro() -> None:
    pasta = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SAR"
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = RotatingFileHandler(pasta / "agente.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    arquivo.setFormatter(FormatoRegistro())
    raiz = logging.getLogger("agente")
    raiz.setLevel(logging.INFO)
    raiz.addHandler(arquivo)


def principal() -> int:
    configurar_registro()
    log = logging.getLogger("agente")
    try:
        config = configuracao.carregar()
    except configuracao.ConfiguracaoInvalida as erro:
        log.error(f"configuracao.invalida: {erro}")  # mensagem nossa, sem dado de paciente
        print(f"Agente de captura: {erro}", file=sys.stderr)
        return 1
    from agente_captura.wia import ScannerWia

    if config.desenvolvimento:
        log.warning("agente.desenvolvimento")  # DD-100: HTTP aceito; nunca na configuração de produção
    contexto = contexto_tls(config.certificado_raiz) if config.servidor.startswith("https://") else None
    captura = Captura(ScannerWia(config.scanner), Enviador(config.servidor, contexto))

    try:
        servidor = ServidorAgente(config.porta, config.origem_permitida, captura.executar)
    except OSError:
        log.error("servidor.porta_ocupada")  # outro agente já aberto nesta sessão, ou porta em uso
        print(f"Agente de captura: a porta {config.porta} já está em uso.", file=sys.stderr)
        return 1
    log.info("agente.iniciado")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
