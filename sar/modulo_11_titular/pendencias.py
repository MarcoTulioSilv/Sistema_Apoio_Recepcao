"""Pendência do MOD-11 (DDS §11.1, linha 10; DD-54): pedido de titular aberto, com o prazo visível; alta, e urgência a
3 dias do prazo. Para recepção, administração e visualizador; nunca para o TI (RF-1004)."""

from __future__ import annotations

from collections.abc import Sequence

from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_08_dados.interfaces.titular import RepositorioTitular
from sar.modulo_11_titular import regras
from sar.modulo_11_titular.contrato import SituacaoRequisicao, TipoRequisicao
from sar.modulo_11_titular.servicos import data_local, dias_do_prazo, hoje
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import FontePendencia, ItemPendencia, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho

TIPOS = {
    TipoRequisicao.CONFIRMACAO_ACESSO: "confirmação e acesso",
    TipoRequisicao.CORRECAO: "correção",
    TipoRequisicao.INFORMACAO: "informação sobre uso e compartilhamento",
    TipoRequisicao.ELIMINACAO: "eliminação, anonimização ou bloqueio",
    TipoRequisicao.OUTROS: "outros",
}


class FontePedidoTitular:
    codigo = "pedido_titular"
    perfis = frozenset({Perfil.RECEPCAO, Perfil.ADMINISTRACAO, Perfil.VISUALIZADOR})

    def __init__(self, leitura: LeituraCadastro, parametros: LeitorParametros) -> None:
        self._leitura = leitura
        self._parametros = parametros

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
        abertas = uow.repositorio(RepositorioTitular).listar(SituacaoRequisicao.ABERTA.value)
        if ids is not None:
            abertas = [a for a in abertas if a.paciente_id in set(ids)]
        vivos = self._leitura.identificacoes(uow, sorted({a.paciente_id for a in abertas}))
        dias, data = dias_do_prazo(self._parametros), hoje(contexto)
        itens = []
        for pedido in abertas:
            if pedido.paciente_id not in vivos:
                continue
            prazo = regras.prazo(data_local(pedido.recebida_em), dias)
            prioridade = Prioridade.URGENCIA if regras.urgente(prazo, data) else Prioridade.ALTA
            descricao = f"Pedido do titular ({TIPOS[TipoRequisicao(pedido.tipo)]}), prazo até {prazo:%d/%m/%Y}"
            itens.append(ItemPendencia(self.codigo, prioridade, pedido.recebida_em, descricao,
                                       f"/titular/{pedido.id}", pedido.paciente_id))  # fmt: skip
        return itens


def fontes(leitura: LeituraCadastro, parametros: LeitorParametros) -> tuple[FontePendencia, ...]:
    return (FontePedidoTitular(leitura, parametros),)
