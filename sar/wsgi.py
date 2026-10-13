"""Ponto de entrada do processo web, servido pelo Waitress atrás do Caddy. Monta a aplicação a partir do
ambiente: banco pelo usuário sar_web (DD-58), chave mestra do segredo, origem e superusuários.

  SAR_AMBIENTE        desenvolvimento ou producao (padrão: producao, DD-85)
  SAR_ORIGEM          esquema://servidor[:porta] exato da página do SAR (DD-80, DD-84); em produção, HTTPS
  SAR_SUPERUSUARIOS   logins separados por vírgula; só em desenvolvimento, senão o servidor não sobe (DD-85).
                      Login que não existe também impede a subida, com o nome dele na mensagem.
  SAR_PROXIES         quantos proxies confiáveis na frente (Caddy: 1); padrão 0
"""

from __future__ import annotations

import os

from flask import Flask
from waitress import serve

from sar.composicao import Ambiente, ambiente_atual, compor, ids_dos_logins
from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.modulo_08_dados.cifra import carregar_chave_mestra
from sar.nucleo.logs import configurar
from sar.web import criar_app
from sar.web.configuracao import ConfigWeb, ServicosWeb

ORIGEM_DESENVOLVIMENTO = "http://127.0.0.1:8080"


def montar() -> Flask:
    configurar("web")  # antes de criar a aplicação, para o Flask não instalar o handler padrão dele
    desenvolvimento = ambiente_atual() is Ambiente.DESENVOLVIMENTO
    origem = os.environ.get("SAR_ORIGEM") or (ORIGEM_DESENVOLVIMENTO if desenvolvimento else "")
    if not origem:
        raise RuntimeError("SAR_ORIGEM é obrigatória fora do desenvolvimento (DD-80)")
    logins = [login.strip().lower() for login in os.environ.get("SAR_SUPERUSUARIOS", "").split(",") if login.strip()]
    if logins and not desenvolvimento:
        raise RuntimeError("SAR_SUPERUSUARIOS só vale em desenvolvimento: o servidor não sobe assim (DD-85)")
    engine = criar_engine(ConfigBanco.do_ambiente("sar_web"))
    componentes = compor(engine, carregar_chave_mestra())
    superusuarios = ids_dos_logins(componentes.executar, logins) if logins else {}
    faltando = sorted(set(logins) - superusuarios.keys())
    if faltando:
        # Ignorar em silêncio deixaria a pessoa sem o seletor de perfil e sem saber por quê.
        raise RuntimeError(
            f"SAR_SUPERUSUARIOS cita login que não existe no banco: {', '.join(faltando)}. "
            "Confira a grafia (ponto e sublinhado contam) ou crie com sar criar-superusuario."
        )
    config = ConfigWeb(
        origem=origem,
        desenvolvimento=desenvolvimento,
        superusuarios=frozenset(superusuarios.values()),
        proxies_confiaveis=int(os.environ.get("SAR_PROXIES", "0")),
    )
    servicos = ServicosWeb(
        componentes.autenticacao,
        componentes.sessoes,
        componentes.usuarios,
        componentes.configuracao,
        componentes.autorizacoes,
        componentes.auditoria,
        componentes.integridade,
    )
    return criar_app(servicos, config)


def main() -> None:
    serve(montar(), host=os.environ.get("SAR_WEB_HOST", "127.0.0.1"), port=int(os.environ.get("SAR_WEB_PORTA", "8080")))


if __name__ == "__main__":
    main()
