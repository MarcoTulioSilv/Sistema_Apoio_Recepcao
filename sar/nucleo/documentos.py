"""Tipos fixos de documento (DEC-41, RF-1203) que o código precisa conhecer. A tabela tipo_documento, carregada
pela migração 0002, é a fonte do nome, da família e da retenção; aqui fica só o que regra de negócio consulta, e
um teste confere que os dois lados concordam."""

from __future__ import annotations

# DEC-53: documento comprobatório exigido por tipo de evento (ERS §3.2.6).
DOCUMENTO_DO_EVENTO: dict[str, str] = {
    "obito": "certidao_obito",
    "alta": "documento_alta",
    "transferencia": "encaminhamento_transferencia",
    "transplante": "documento_transplante",
    "desistencia": "termo_interrupcao",
}

# Termos assinados que o MOD-03 liga à troca e ao mês do paciente (RF-805, RF-809).
DOCUMENTO_DA_TROCA = "declaracao_troca"  # DOC-03
DOCUMENTO_DA_EXTRA = "termo_extra"  # DOC-07
