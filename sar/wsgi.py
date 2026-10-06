"""Ponto de entrada do processo web, servido pelo Waitress atrás do Caddy."""

from __future__ import annotations

import os

from waitress import serve

from sar.nucleo.logs import configurar
from sar.web import criar_app

configurar("web")  # antes de criar a aplicação, para o Flask não instalar o handler padrão dele
app = criar_app()


def main() -> None:
    serve(app, host=os.environ.get("SAR_WEB_HOST", "127.0.0.1"), port=int(os.environ.get("SAR_WEB_PORTA", "8080")))


if __name__ == "__main__":
    main()
