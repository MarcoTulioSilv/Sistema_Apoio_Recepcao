"""Tabelas fixas do SAR: escalas (DEC-52, P-14), tipos de documento (DEC-41, P-16), faixas etárias
(DEC-49), municípios do IBGE (RF-1205) e a cabeça da cadeia de auditoria (DD-03).

A tabela de municípios vem do arquivo oficial do IBGE (Divisão Territorial Brasileira), convertido para
CSV com três colunas — codigo_ibge;nome;uf — e códigos de 7 dígitos. O caminho padrão é
dados/municipios_ibge.csv; pode ser trocado pela variável SAR_MUNICIPIOS_CSV.

Revision ID: 0002
"""
import csv
import os
import re
from datetime import time
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MINIMO_MUNICIPIOS = int(os.environ.get("SAR_MUNICIPIOS_MINIMO", "5570"))

ESCALAS = [
    # id, código, turno, dias, início, fim
    (1, "1-seg", 1, "seg,qua,sex", time(6, 0), time(10, 0)),
    (2, "1-ter", 1, "ter,qui,sab", time(6, 0), time(10, 0)),
    (3, "2-seg", 2, "seg,qua,sex", time(11, 0), time(15, 0)),
    (4, "2-ter", 2, "ter,qui,sab", time(11, 0), time(15, 0)),
    (5, "3-seg", 3, "seg,qua,sex", time(16, 0), time(20, 0)),
    (6, "3-ter", 3, "ter,qui,sab", time(16, 0), time(20, 0)),
]

TIPOS_DOCUMENTO = [
    # código, nome, família, checklist, evento exigente, origem, campos de extração
    ("comprovante_endereco", "Comprovante de endereço", "cadastro", "sempre", None, "scanner", "cep"),
    ("cartao_sus", "Cartão do SUS", "cadastro", "sempre", None, "scanner", "cns"),
    ("cartao_convenio", "Cartão do convênio", "cadastro", "se_convenio", None, "scanner", "carteirinha"),
    ("documento_identidade", "Documento de identidade", "cadastro", "nao", None, "scanner", "cpf,data_nascimento"),
    ("foto_paciente", "Foto do paciente", "cadastro", "nao", None, "webcam", None),
    ("certidao_obito", "Certidão de óbito", "prontuario", "nao", "obito", "scanner", None),
    ("documento_alta", "Documento de alta", "prontuario", "nao", "alta", "scanner", None),
    ("encaminhamento_transferencia", "Encaminhamento de transferência", "prontuario", "nao", "transferencia",
     "scanner", None),
    ("documento_transplante", "Documento do centro transplantador", "prontuario", "nao", "transplante",
     "scanner", None),
    ("termo_interrupcao", "Termo de interrupção do tratamento assinado (DOC-06)", "prontuario", "nao",
     "desistencia", "scanner", None),
    ("declaracao_troca", "Declaração de troca de turno assinada (DOC-03)", "prontuario", "nao", None, "scanner", None),
    ("termo_extra", "Termo de diálise extra assinado (DOC-07)", "prontuario", "nao", None, "scanner", None),
    ("termo_cateter", "Termo de cateter assinado (DOC-02)", "prontuario", "nao", None, "scanner", None),
    ("termo_alimentos", "Termo de alimentos assinado (DOC-04)", "prontuario", "nao", None, "scanner", None),
    ("carta_recusa", "Carta de recusa assinada (DOC-05)", "prontuario", "nao", None, "scanner", None),
]
ANOS_RETENCAO = 20  # P-16, contados como na DD-01

FAIXAS = [(i * 10, i * 10 + 9, f"{i * 10} a {i * 10 + 9}") for i in range(10)] + [(100, None, "100 ou mais")]


def _municipios() -> list[dict]:
    caminho = Path(os.environ.get("SAR_MUNICIPIOS_CSV", "dados/municipios_ibge.csv"))
    if not caminho.exists():
        raise RuntimeError(f"Arquivo de municípios não encontrado: {caminho}. Gere-o a partir da DTB do IBGE.")
    linhas = []
    with caminho.open(encoding="utf-8", newline="") as f:
        for n, (codigo, nome, uf) in enumerate(csv.reader(f, delimiter=";"), start=1):
            codigo, nome, uf = codigo.strip(), nome.strip(), uf.strip().upper()
            if n == 1 and not codigo.isdigit():
                continue  # cabeçalho
            if not re.fullmatch(r"\d{7}", codigo) or not re.fullmatch(r"[A-Z]{2}", uf) or not nome:
                raise RuntimeError(f"Linha {n} do arquivo de municípios inválida")
            linhas.append({"codigo_ibge": codigo, "nome": nome, "uf": uf})
    if len(linhas) < MINIMO_MUNICIPIOS:
        raise RuntimeError(f"Arquivo de municípios com {len(linhas)} linhas; esperado ao menos {MINIMO_MUNICIPIOS}")
    return linhas


def upgrade() -> None:
    meta = sa.MetaData()
    escala = sa.Table("escala", meta, autoload_with=op.get_bind())
    tipo = sa.Table("tipo_documento", meta, autoload_with=op.get_bind())
    faixa = sa.Table("faixa_etaria", meta, autoload_with=op.get_bind())
    municipio = sa.Table("municipio", meta, autoload_with=op.get_bind())
    cabeca = sa.Table("auditoria_cabeca", meta, autoload_with=op.get_bind())

    op.bulk_insert(escala, [dict(id=i, codigo=c, turno=t, dias=d, hora_inicio=a, hora_fim=b)
                            for i, c, t, d, a, b in ESCALAS])
    op.bulk_insert(tipo, [dict(codigo=c, nome=n, familia=f, anos_retencao=ANOS_RETENCAO, checklist=k,
                               evento_exigente=e, origem=o, campos_extracao=x)
                          for c, n, f, k, e, o, x in TIPOS_DOCUMENTO])
    op.bulk_insert(faixa, [dict(inicio=a, fim=b, rotulo=r) for a, b, r in FAIXAS])
    op.bulk_insert(municipio, _municipios())
    # Primeiro elo da cadeia: hash anterior de 64 zeros (§3.10, item 5)
    op.bulk_insert(cabeca, [dict(id=1, ultimo_registro_id=0, ultimo_hash="0" * 64)])


def downgrade() -> None:
    for tabela in ["auditoria_cabeca", "municipio", "faixa_etaria", "tipo_documento", "escala"]:
        op.execute(f"DELETE FROM {tabela}")
