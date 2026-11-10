"""Pendências do MOD-01 (DDS §11.1, linhas 11 e 12; DD-54). Como as demais fontes, nada devolvem a quem não vê a
linha, mesmo antes do filtro do MOD-07."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sar.modulo_08_dados.interfaces.autorizacoes import DadosSolicitacao, RepositorioAutorizacao
from sar.modulo_08_dados.interfaces.trilha import RepositorioTrilha
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.portas import ExecutorAutorizavel, FontePendencia, ItemPendencia, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho


def _paciente(solicitacao: DadosSolicitacao) -> int | None:
    """Os serviços que pedem autorização sobre um paciente levam o id nos parâmetros (só identificadores)."""
    valor = solicitacao.parametros.get("paciente_id")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


class FonteSolicitacaoAutorizacao:
    """Linha 11: solicitação aguardando a decisão da administração (RF-1008, DEC-42)."""

    codigo = "solicitacao_autorizacao"
    prioridade = Prioridade.ALTA

    def __init__(self, executores: Mapping[str, ExecutorAutorizavel]) -> None:
        self._executores = executores

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        if contexto.perfil is not Perfil.ADMINISTRACAO:
            return 0
        return len(uow.repositorio(RepositorioAutorizacao).listar("pendente"))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        if contexto.perfil is not Perfil.ADMINISTRACAO:
            return []
        return [self._item(uow, s) for s in uow.repositorio(RepositorioAutorizacao).listar("pendente")]

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        if contexto.perfil is not Perfil.ADMINISTRACAO or not paciente_ids:
            return []
        alvo = set(paciente_ids)
        pendentes = uow.repositorio(RepositorioAutorizacao).listar("pendente")
        return [self._item(uow, s) for s in pendentes if _paciente(s) in alvo]

    def _item(self, uow: UnidadeDeTrabalho, solicitacao: DadosSolicitacao) -> ItemPendencia:
        executor = self._executores.get(solicitacao.tipo)
        descricao = executor.descrever(uow, solicitacao.parametros) if executor else solicitacao.tipo
        return ItemPendencia(self.codigo, self.prioridade, solicitacao.solicitada_em, descricao,
                             f"/autorizacoes/{solicitacao.id}", _paciente(solicitacao))  # fmt: skip


class FonteFalhaCadeia:
    """Linha 12: aviso de integridade aberto (RF-1011). A administração vê o aviso simples; o TI, o diagnóstico com o
    registro divergente, que é identificador interno da trilha. Encerra quando a administração encerra o aviso."""

    codigo = "falha_cadeia"
    prioridade = Prioridade.URGENCIA

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        if contexto.perfil not in (Perfil.ADMINISTRACAO, Perfil.TI):
            return []
        itens = []
        for aviso in uow.repositorio(RepositorioTrilha).avisos_abertos():
            if contexto.perfil is Perfil.TI:
                descricao = f"Cadeia de auditoria divergente a partir do registro {aviso.registro_divergente_id}"
                identificador: str | None = str(aviso.registro_divergente_id)
            else:
                descricao, identificador = "A verificação da trilha de auditoria encontrou uma divergência", None
            itens.append(ItemPendencia(self.codigo, self.prioridade, aviso.detectado_em, descricao, "/integridade",
                                       identificador_interno=identificador))  # fmt: skip
        return itens

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        return []


def fontes(executores: Mapping[str, ExecutorAutorizavel]) -> tuple[FontePendencia, ...]:
    return (FonteSolicitacaoAutorizacao(executores), FonteFalhaCadeia())
