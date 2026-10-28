"""Pendências do MOD-04 (DDS §11.1, linhas 2, 14, 15, 16 e 18; DD-54). Cada fonte responde ao conjunto numa consulta
só (§11.3) e devolve nada a quem não deve ver a linha, mesmo antes do filtro do MOD-07. O TI só vê identificadores
internos, nunca o paciente (RNF-625)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import ClassVar

from sar.modulo_04_documentos.antimalware import Antimalware, AntimalwareIndisponivel, assinaturas_vencidas
from sar.modulo_04_documentos.retencao import elegiveis
from sar.modulo_08_dados.interfaces.documentos import RepositorioDocumentos
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import FonteChecklist, FonteMarcoRetencao, FontePendencia, ItemPendencia, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho

RECEPCAO_E_ADMINISTRACAO = frozenset({Perfil.RECEPCAO, Perfil.ADMINISTRACAO})
NOMES_CHECKLIST = {"comprovante_endereco": "comprovante de endereço", "cartao_sus": "cartão do SUS",
                   "cartao_convenio": "cartão do convênio"}  # fmt: skip


def _hoje(contexto: Contexto) -> datetime:
    return contexto.instante.astimezone(FUSO_CLINICA)


class _FonteDePaciente:
    """Base das linhas com paciente: contar é listar; por pacientes, só os pedidos."""

    codigo: str
    prioridade: Prioridade
    perfis: frozenset[Perfil] = RECEPCAO_E_ADMINISTRACAO

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        return self._itens(uow, contexto, None) if contexto.perfil in self.perfis else []

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        if contexto.perfil not in self.perfis or not paciente_ids:
            return []
        return self._itens(uow, contexto, paciente_ids)

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        raise NotImplementedError


class FonteChecklistFaltante(_FonteDePaciente):
    """Linha 2: documento do checklist de cadastro que falta a paciente em tratamento (RF-706, RF-707)."""

    codigo = "checklist_faltante"
    prioridade = Prioridade.NORMAL

    def __init__(self, checklist: FonteChecklist) -> None:
        self._checklist = checklist

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        repo = uow.repositorio(RepositorioDocumentos)
        exigencias = self._checklist.exigencias(uow, ids, _hoje(contexto).date())
        if not exigencias:
            return []
        tipos = repo.tipos()
        sempre = [t.codigo for t in tipos if t.checklist == "sempre"]
        se_convenio = [t.codigo for t in tipos if t.checklist == "se_convenio"]
        presentes = repo.tipos_presentes([e.paciente_id for e in exigencias])
        itens = []
        for exigencia in exigencias:
            exigidos = sempre + (se_convenio if exigencia.convenio else [])
            faltam = [c for c in exigidos if c not in presentes.get(exigencia.paciente_id, set())]
            if faltam:
                descricao = "Falta: " + ", ".join(NOMES_CHECKLIST.get(c, c) for c in faltam)
                itens.append(ItemPendencia(self.codigo, self.prioridade, exigencia.desde, descricao,
                                           f"/pacientes/{exigencia.paciente_id}", exigencia.paciente_id))  # fmt: skip
        return itens


class FonteAguardandoConferencia(_FonteDePaciente):
    """Linha 14: documento capturado esperando a conferência; some ao incorporar, rejeitar ou expirar (24 h)."""

    codigo = "aguardando_conferencia"
    prioridade = Prioridade.ALTA

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        repo = uow.repositorio(RepositorioDocumentos)
        alvo = set(ids) if ids is not None else None
        itens = []
        for ingestao in repo.em_estado(["aguardando_conferencia"]):
            if alvo is not None and ingestao.paciente_id not in alvo:
                continue
            tipo = repo.tipo(ingestao.tipo)
            descricao = f"{tipo.nome if tipo else ingestao.tipo} a conferir"
            destino = f"/documentos/conferencia/{ingestao.id.hex()}"
            itens.append(ItemPendencia(self.codigo, self.prioridade, ingestao.atualizada_em, descricao, destino,
                                       ingestao.paciente_id))  # fmt: skip
        return itens


class FonteDocumentoBloqueado:
    """Linha 15: documento bloqueado (P-19). A administração vê o paciente; o TI, só o identificador do documento."""

    codigo = "documento_bloqueado"
    prioridade = Prioridade.URGENCIA
    MOTIVOS: ClassVar[dict[str, str]] = {
        "rescan": "detecção do antimalware na revarredura",
        "hash_divergente": "arquivo alterado no disco",
    }

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        if contexto.perfil not in (Perfil.ADMINISTRACAO, Perfil.TI):
            return []
        itens = []
        for documento in uow.repositorio(RepositorioDocumentos).bloqueados():
            motivo = self.MOTIVOS.get(documento.bloqueio_motivo or "", "bloqueado")
            desde = documento.bloqueado_em or documento.capturado_em
            if contexto.perfil is Perfil.TI:
                itens.append(ItemPendencia(self.codigo, self.prioridade, desde, f"Documento bloqueado: {motivo}",
                                           "/pendencias", identificador_interno=documento.id.hex()))  # fmt: skip
            else:
                itens.append(ItemPendencia(self.codigo, self.prioridade, desde, f"Documento bloqueado: {motivo}",
                                           f"/pacientes/{documento.paciente_id}", documento.paciente_id))  # fmt: skip
        return itens

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        if contexto.perfil is not Perfil.ADMINISTRACAO:
            return []
        alvo = set(paciente_ids)
        return [i for i in self.listar(uow, contexto) if i.paciente_id in alvo]


class FonteElegiveisDescarte(_FonteDePaciente):
    """Linha 16: documentos com o prazo de retenção vencido (DD-01, DD-04), para a administração pedir o descarte."""

    codigo = "elegiveis_descarte"
    prioridade = Prioridade.NORMAL
    perfis = frozenset({Perfil.ADMINISTRACAO})

    def __init__(self, marco: FonteMarcoRetencao) -> None:
        self._marco = marco

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto, ids: Sequence[int] | None) -> list[ItemPendencia]:
        alvo = set(ids) if ids is not None else None
        hoje = _hoje(contexto)
        itens = []
        for elegivel in elegiveis(uow, self._marco, hoje.date()):
            if alvo is not None and elegivel.paciente_id not in alvo:
                continue
            desde = datetime.combine(elegivel.prazo, datetime.min.time(), FUSO_CLINICA)
            itens.append(ItemPendencia(self.codigo, self.prioridade, desde,
                                       f"Retenção vencida em {elegivel.prazo:%d/%m/%Y}: descarte possível",
                                       f"/pacientes/{elegivel.paciente_id}", elegivel.paciente_id))  # fmt: skip
        return itens


class FonteAssinaturasAntimalware:
    """Linha 18: assinaturas do antimalware desatualizadas ou clamd sem resposta (SEG-21, DD-97). Só o TI."""

    codigo = "antimalware_desatualizado"
    prioridade = Prioridade.URGENCIA

    def __init__(self, antimalware: Antimalware, parametros: LeitorParametros) -> None:
        self._antimalware = antimalware
        self._parametros = parametros

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        if contexto.perfil is not Perfil.TI:
            return []
        try:
            versao = self._antimalware.versao()
        except AntimalwareIndisponivel:
            return [ItemPendencia(self.codigo, self.prioridade, contexto.instante,
                                  "Antimalware sem resposta: a digitalização está parada", "/pendencias")]  # fmt: skip
        idade = self._parametros.valor("antimalware_idade_maxima")
        if isinstance(idade, int) and assinaturas_vencidas(versao, contexto.instante, idade):
            descricao = f"Assinaturas do antimalware de {versao.assinaturas_em.astimezone(FUSO_CLINICA):%d/%m/%Y %H:%M}"
            return [ItemPendencia(self.codigo, self.prioridade, versao.assinaturas_em, descricao, "/pendencias")]
        return []

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        return []


def fontes(
    checklist: FonteChecklist, marco: FonteMarcoRetencao, antimalware: Antimalware, parametros: LeitorParametros
) -> tuple[FontePendencia, ...]:
    return (
        FonteChecklistFaltante(checklist),
        FonteAguardandoConferencia(),
        FonteDocumentoBloqueado(),
        FonteElegiveisDescarte(marco),
        FonteAssinaturasAntimalware(antimalware, parametros),
    )
