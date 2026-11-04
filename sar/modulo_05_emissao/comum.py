"""O que todo modelo recebe (RF-802, RF-803, DD-86): o cabeçalho institucional, o logotipo, a data por extenso com o
município e o código de integridade do rodapé. Lido dentro da unidade de trabalho de quem chama."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_05_emissao import regras
from sar.modulo_06_configuracao.contrato import Referencias
from sar.nucleo.uow import UnidadeDeTrabalho

# Prévia antes de a administração informar os dados institucionais (DD-42): nada disso sai numa emissão.
INSTITUICAO_FICTICIA = {
    "clinica_nome": "Clínica Exemplo",
    "clinica_endereco": "Rua Exemplo, 100 - Centro",
    "clinica_cep": "75800-000",
    "clinica_municipio": "Jataí",
    "clinica_uf": "GO",
    "clinica_telefone": "(64) 3600-0000",
    "clinica_cnpj": "",
}


@dataclass(frozen=True, slots=True)
class Comuns:
    valores: dict[str, str]
    logotipo: bytes | None
    configurada: bool  # False: a instituição ainda não foi informada (RF-1201)


def ler(uow: UnidadeDeTrabalho, referencias: Referencias, auditoria: AuditService, instante: datetime) -> Comuns:
    instituicao = referencias.institucional(uow)
    if instituicao is None:
        valores = dict(INSTITUICAO_FICTICIA)
    else:
        valores = {
            "clinica_nome": instituicao.nome,
            "clinica_endereco": instituicao.endereco,
            "clinica_cep": regras.cep(instituicao.cep),
            "clinica_municipio": instituicao.municipio.nome,
            "clinica_uf": instituicao.municipio.uf,
            "clinica_telefone": regras.telefone(instituicao.telefone),
            "clinica_cnpj": regras.cnpj(instituicao.cnpj),
        }
    valores["data_extenso"] = regras.data_extenso(valores["clinica_municipio"], regras.hoje(instante))
    codigo = auditoria.codigo_vigente(uow)
    valores["codigo_integridade"] = (
        regras.codigo_integridade(codigo.registro_id, codigo.codigo, codigo.registrada_em) if codigo else ""
    )
    logotipo = referencias.logotipo(uow) if instituicao is not None and instituicao.tem_logotipo else None
    return Comuns(valores, logotipo, instituicao is not None)
