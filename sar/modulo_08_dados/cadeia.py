"""Gravação encadeada da trilha de auditoria (DD-03, DD-71). Fica no MOD-08 porque é SQL; a forma canônica
está em canonico.py, e a verificação, o aviso e o expurgo são do MOD-01."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.canonico import (
    VERSAO_FORMATO,
    calcular_hash,
    json_do_registro,
    serializar_alteracoes,
)
from sar.modulo_08_dados.modelos.acesso import Auditoria, AuditoriaCabeca
from sar.nucleo.uow import RegistroAuditoria


def json_da_linha(linha: Auditoria) -> str:
    """O JSON canônico reconstruído da linha gravada (o banco devolve o instante sem fuso, em UTC)."""
    if linha.versao_formato != VERSAO_FORMATO:
        raise ValueError(f"versão de formato desconhecida: {linha.versao_formato}")
    return json_do_registro(
        id=linha.id,
        instante=linha.instante.replace(tzinfo=UTC),
        usuario_id=linha.usuario_id,
        autorizador_id=linha.autorizador_id,
        operacao=linha.operacao,
        entidade=linha.entidade,
        entidade_id=linha.entidade_id,
        alteracoes=linha.alteracoes,
        motivo=linha.motivo,
        origem=linha.origem,
        sessao_id=linha.sessao_id,
        requisicao_id=linha.requisicao_id,
        versao_formato=linha.versao_formato,
    )


def gravar_encadeado(sessao: Session, registros: Sequence[RegistroAuditoria]) -> None:
    """O gravador de auditoria real: última operação antes do commit (DD-03). A trava da cabeça serializa web e
    worker; o id vem dela (DD-71). Se qualquer passo falhar, a operação inteira é desfeita."""
    cabeca = sessao.execute(select(AuditoriaCabeca).where(AuditoriaCabeca.id == 1).with_for_update()).scalar_one()
    ultimo_id, ultimo_hash = cabeca.ultimo_registro_id, cabeca.ultimo_hash
    for registro in registros:
        ultimo_id += 1
        contexto = registro.contexto
        linha = Auditoria(
            id=ultimo_id,
            instante=contexto.instante.astimezone(UTC).replace(tzinfo=None),
            usuario_id=contexto.usuario_id,
            autorizador_id=registro.autorizador_id,
            operacao=registro.operacao,
            entidade=registro.entidade,
            entidade_id=registro.entidade_id,
            alteracoes=serializar_alteracoes(registro.alteracoes),
            motivo=registro.motivo,
            origem=contexto.origem,
            sessao_id=contexto.sessao_id,
            requisicao_id=contexto.requisicao_id,
            versao_formato=VERSAO_FORMATO,
            hash_anterior=ultimo_hash,
        )
        # O hash sai da própria linha, pelo mesmo caminho que a verificação usa.
        linha.hash_registro = calcular_hash(ultimo_hash, json_da_linha(linha))
        sessao.add(linha)
        ultimo_hash = linha.hash_registro
    sessao.flush()
    sessao.execute(
        update(AuditoriaCabeca)
        .where(AuditoriaCabeca.id == 1)
        .values(ultimo_registro_id=ultimo_id, ultimo_hash=ultimo_hash)
    )
