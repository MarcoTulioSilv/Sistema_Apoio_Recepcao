"""Regras puras do MOD-07 (DDS §11): quem vê o quê, em que ordem, e a contagem por tipo da tela inicial."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from sar.modulo_07_pendencias.matriz import POR_CODIGO
from sar.nucleo.contexto import Perfil
from sar.nucleo.portas import ItemPendencia, Prioridade

ORDEM_PRIORIDADE = {Prioridade.URGENCIA: 0, Prioridade.ALTA: 1, Prioridade.NORMAL: 2}


def ve(perfil: Perfil, codigo: str) -> bool:
    linha = POR_CODIGO.get(codigo)
    return linha is not None and perfil in linha.perfis


def filtrar(itens: Iterable[ItemPendencia], perfil: Perfil) -> list[ItemPendencia]:
    """Só as linhas do perfil (ERS §3.2.13). Para o TI, nunca um item com paciente (RF-1004, RNF-625): a fonte que
    errar perde o item, em vez de vazar o dado."""
    return [
        item for item in itens if ve(perfil, item.codigo) and not (perfil is Perfil.TI and item.paciente_id is not None)
    ]


def ordenar(itens: Iterable[ItemPendencia]) -> list[ItemPendencia]:
    """Urgência no topo, depois alta, depois normal; dentro da mesma prioridade, a mais antiga primeiro (RNF-408)."""
    return sorted(itens, key=lambda i: (ORDEM_PRIORIDADE[i.prioridade], i.desde, POR_CODIGO[i.codigo].numero))


def contar_por_tipo(itens: Iterable[ItemPendencia]) -> list[tuple[str, Prioridade, int]]:
    """(código, prioridade, quantidade), urgências primeiro e na ordem da matriz. Uma linha de prioridade variável
    aparece uma vez por prioridade que tiver."""
    contagem = Counter((i.codigo, i.prioridade) for i in itens)
    return ordenar_contagens([(codigo, prioridade, n) for (codigo, prioridade), n in contagem.items()])


def ordenar_contagens(contagens: Iterable[tuple[str, Prioridade, int]]) -> list[tuple[str, Prioridade, int]]:
    return sorted(contagens, key=lambda c: (ORDEM_PRIORIDADE[c[1]], POR_CODIGO[c[0]].numero))


def por_paciente(itens: Iterable[ItemPendencia], ids: Sequence[int]) -> dict[int, list[ItemPendencia]]:
    """Os itens de cada paciente pedido, ordenados; quem não tem pendência recebe lista vazia."""
    grupos: dict[int, list[ItemPendencia]] = {paciente_id: [] for paciente_id in ids}
    for item in itens:
        if item.paciente_id in grupos:
            grupos[item.paciente_id].append(item)
    return {paciente_id: ordenar(lista) for paciente_id, lista in grupos.items()}


def totais(contagens: Iterable[tuple[str, Prioridade, int]]) -> Mapping[Prioridade, int]:
    """Total por prioridade, com as três sempre presentes (o bloco da tela inicial)."""
    soma = dict.fromkeys(Prioridade, 0)
    for _, prioridade, quantidade in contagens:
        soma[prioridade] += quantidade
    return soma
