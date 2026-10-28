"""Configuração da estação (§8.5): um arquivo JSON editável só pelo TI, nunca pela requisição (DD-39).

Local padrão: %PROGRAMDATA%\\SAR\\agente.json (a instalação deixa a pasta só com leitura para a recepção).
`SAR_AGENTE_CONFIG` aponta para outro arquivo, para teste.

    {
      "servidor": "https://sar.clinica.local",
      "certificado_raiz": "C:\\\\ProgramData\\\\SAR\\\\raiz.crt",
      "scanner": "Brother DCP-L2540DW",
      "porta": 47830
    }

A origem permitida é a do próprio servidor (DD-39); `origem` só existe para o caso de a página ser servida por outro
nome do mesmo servidor. `"desenvolvimento": true` aceita servidor em HTTP, sem certificado, só para a homologação
antes do HTTPS da implantação (DD-100); a configuração de produção não tem essa chave.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PORTA_PADRAO = 47830  # DD-98


class ConfiguracaoInvalida(Exception):
    """Arquivo ausente, ilegível ou com valor fora do formato. A mensagem diz o que corrigir."""


@dataclass(frozen=True, slots=True)
class Configuracao:
    servidor: str  # https://servidor[:porta], sem caminho
    certificado_raiz: Path  # autoridade interna da clínica: a única em que o agente confia (certificado fixado)
    scanner: str  # nome do scanner no WIA (DD-79)
    porta: int = PORTA_PADRAO
    origem: str = ""  # vazio: a do servidor
    desenvolvimento: bool = False  # DD-100: HTTP aceito, para medir na homologação

    @property
    def origem_permitida(self) -> str:
        return (self.origem or self.servidor).rstrip("/")


def _origem(valor: str, campo: str, desenvolvimento: bool) -> str:
    partes = urlsplit(valor)
    esquemas = ("https", "http") if desenvolvimento else ("https",)
    if partes.scheme not in esquemas or not partes.netloc or partes.path not in ("", "/") or partes.query:
        raise ConfiguracaoInvalida(f"{campo} deve ser https://servidor[:porta], sem caminho (DD-80)")
    return valor.rstrip("/")


def de_dicionario(dados: dict[str, object]) -> Configuracao:
    desenvolvimento = dados.get("desenvolvimento") is True
    try:
        servidor = _origem(str(dados["servidor"]), "servidor", desenvolvimento)
        https = servidor.startswith("https://")
        raiz = Path(str(dados["certificado_raiz"])) if https or dados.get("certificado_raiz") else Path()
        scanner = str(dados["scanner"]).strip()
        porta = int(str(dados.get("porta", PORTA_PADRAO)))
        origem = _origem(str(dados["origem"]), "origem", desenvolvimento) if dados.get("origem") else ""
    except KeyError as falta:
        raise ConfiguracaoInvalida(f"falta o campo {falta.args[0]} na configuração do agente") from None
    except ValueError:
        raise ConfiguracaoInvalida("a porta do agente deve ser um número") from None
    if not scanner:
        raise ConfiguracaoInvalida("informe o nome do scanner, como aparece no WIA (DD-79)")
    if not 1024 <= porta <= 65535:
        raise ConfiguracaoInvalida("a porta do agente deve estar entre 1024 e 65535")
    if https and not raiz.is_file():
        raise ConfiguracaoInvalida(f"certificado raiz não encontrado: {raiz}")
    return Configuracao(servidor, raiz, scanner, porta, origem, desenvolvimento)


def caminho_padrao() -> Path:
    if os.environ.get("SAR_AGENTE_CONFIG"):
        return Path(os.environ["SAR_AGENTE_CONFIG"])
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SAR" / "agente.json"


def carregar(caminho: Path | None = None) -> Configuracao:
    caminho = caminho or caminho_padrao()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfiguracaoInvalida(f"configuração do agente não encontrada: {caminho}") from None
    except OSError, ValueError:
        raise ConfiguracaoInvalida(f"configuração do agente ilegível: {caminho}") from None
    if not isinstance(dados, dict):
        raise ConfiguracaoInvalida(f"configuração do agente ilegível: {caminho}")
    return de_dicionario(dados)
