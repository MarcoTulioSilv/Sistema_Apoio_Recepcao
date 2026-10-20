"""Retenção derivada (DD-01): nenhuma coluna de prazo. Com período de tratamento aberto, não há prazo; encerrado o
último período, o marco é a data mais recente entre o evento de encerramento (pelo MOD-02, `FonteMarcoRetencao`) e
o último documento do paciente; o prazo é o marco somado aos anos de retenção do tipo. Vencido, o documento fica
elegível para descarte (DD-04), nunca é descartado sozinho."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sar.modulo_08_dados.interfaces.documentos import DocumentoGravado, RepositorioDocumentos
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.portas import FonteMarcoRetencao, MarcoRetencao
from sar.nucleo.uow import UnidadeDeTrabalho


@dataclass(frozen=True, slots=True)
class Elegivel:
    documento_id: bytes
    paciente_id: int
    tipo: str
    prazo: date


def _data(instante: datetime) -> date:
    return instante.astimezone(FUSO_CLINICA).date()


def somar_anos(dia: date, anos: int) -> date:
    """29 de fevereiro vira 28 no ano sem o dia."""
    try:
        return dia.replace(year=dia.year + anos)
    except ValueError:
        return dia.replace(year=dia.year + anos, day=28)


def prazo(marco: MarcoRetencao, ultimo_documento: datetime | None, anos: int) -> date | None:
    """None enquanto houver período aberto, ou sem nenhum registro para contar."""
    if marco.em_tratamento:
        return None
    datas = [d for d in (marco.ultimo_encerramento, _data(ultimo_documento) if ultimo_documento else None) if d]
    return somar_anos(max(datas), anos) if datas else None


def prazo_do_documento(uow: UnidadeDeTrabalho, fonte: FonteMarcoRetencao, documento: DocumentoGravado) -> date | None:
    repo = uow.repositorio(RepositorioDocumentos)
    tipo = repo.tipo(documento.tipo)
    ultimo = repo.ultimo_documento_em([documento.paciente_id]).get(documento.paciente_id)
    return prazo(fonte.marco(uow, documento.paciente_id), ultimo, tipo.anos_retencao if tipo else 20)


def elegiveis(uow: UnidadeDeTrabalho, fonte: FonteMarcoRetencao, hoje: date) -> list[Elegivel]:
    """Os não descartados cujo prazo já venceu, dos mais antigos aos mais novos."""
    repo = uow.repositorio(RepositorioDocumentos)
    por_paciente: dict[int, list[DocumentoGravado]] = defaultdict(list)
    for documento in repo.nao_descartados():
        por_paciente[documento.paciente_id].append(documento)
    ultimos = repo.ultimo_documento_em(list(por_paciente))
    anos = {}
    resultado = []
    for paciente_id, documentos in por_paciente.items():
        marco = fonte.marco(uow, paciente_id)
        for documento in documentos:
            if documento.tipo not in anos:
                tipo = repo.tipo(documento.tipo)
                anos[documento.tipo] = tipo.anos_retencao if tipo else 20
            vence = prazo(marco, ultimos.get(paciente_id), anos[documento.tipo])
            if vence is not None and vence <= hoje:
                resultado.append(Elegivel(documento.id, paciente_id, documento.tipo, vence))
    return sorted(resultado, key=lambda e: (e.prazo, e.documento_id))
