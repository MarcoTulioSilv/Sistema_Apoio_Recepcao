"""Serviço de pendências (DDS §11, RF-1010): junta as fontes dos módulos (DD-54), filtra pela matriz (DD-55) e ordena.

Consulta só as fontes das linhas que o perfil vê, todas na mesma unidade de trabalho. Não audita: o detalhe de cada
item segue a auditoria do módulo dono (DDS §4.7).
"""

from __future__ import annotations

from collections.abc import Sequence

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_07_pendencias import regras
from sar.modulo_07_pendencias.contrato import ContagemTipo, Resumo
from sar.modulo_07_pendencias.matriz import MATRIZ, POR_CODIGO
from sar.modulo_08_dados.interfaces.pacientes import RepositorioPaciente
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado
from sar.nucleo.portas import FontePendencia, ItemPendencia, Prioridade
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
OPERACAO = "pendencia.ver"


class ServicoPendencias:
    def __init__(self, executar: ExecutorDeOperacao, fontes: Sequence[FontePendencia]) -> None:
        codigos = [fonte.codigo for fonte in fontes]
        desconhecidos = sorted(set(codigos) - POR_CODIGO.keys())
        repetidos = sorted({c for c in codigos if codigos.count(c) > 1})
        if desconhecidos or repetidos:  # erro de composição, não de uso
            raise ValueError(f"fontes fora da matriz {desconhecidos} ou repetidas {repetidos}")
        self._executar = executar
        ordem = {linha.codigo: linha.numero for linha in MATRIZ}
        self._fontes = tuple(sorted(fontes, key=lambda f: ordem[f.codigo]))

    def _do_perfil(self, contexto: Contexto) -> tuple[FontePendencia, ...]:
        return tuple(f for f in self._fontes if regras.ve(contexto.perfil, f.codigo))

    def resumo(self, contexto: Contexto) -> Resumo:
        GUARDA.exigir(contexto, OPERACAO)
        fontes = self._do_perfil(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> list[tuple[str, Prioridade, int]]:
            contagens: list[tuple[str, Prioridade, int]] = []
            for fonte in fontes:
                linha = POR_CODIGO[fonte.codigo]
                if linha.variavel:  # a prioridade de cada item só aparece listando
                    itens = regras.filtrar(fonte.listar(uow, contexto), contexto.perfil)
                    contagens.extend(regras.contar_por_tipo(itens))
                elif quantidade := fonte.contar(uow, contexto):
                    contagens.append((fonte.codigo, linha.prioridade, quantidade))
            return contagens

        contagens = regras.ordenar_contagens(self._executar(operacao))
        tipos = tuple(ContagemTipo(c, POR_CODIGO[c].nome, p, q) for c, p, q in contagens)
        return Resumo(tipos, regras.totais(contagens))

    def listar(self, contexto: Contexto, codigo: str | None = None) -> list[ItemPendencia]:
        GUARDA.exigir(contexto, OPERACAO)
        fontes = self._do_perfil(contexto)
        if codigo is not None:
            if not regras.ve(contexto.perfil, codigo):
                raise AcessoNegado()
            fontes = tuple(f for f in fontes if f.codigo == codigo)

        def operacao(uow: UnidadeDeTrabalho) -> list[ItemPendencia]:
            return [item for fonte in fontes for item in fonte.listar(uow, contexto)]

        return regras.ordenar(regras.filtrar(self._executar(operacao), contexto.perfil))

    def nomes(self, contexto: Contexto, itens: Sequence[ItemPendencia]) -> dict[int, str]:
        GUARDA.exigir(contexto, OPERACAO)
        ids = sorted({i.paciente_id for i in itens if i.paciente_id is not None})
        if contexto.perfil is Perfil.TI or not ids:
            return {}
        vivos = self._executar(lambda uow: uow.repositorio(RepositorioPaciente).vivos(ids))
        return {p.id: p.campos.nome for p in vivos if p.campos.nome}

    def dos_pacientes(self, contexto: Contexto, ids: Sequence[int]) -> dict[int, list[ItemPendencia]]:
        GUARDA.exigir(contexto, OPERACAO)
        unicos = list(dict.fromkeys(ids))
        fontes = tuple(f for f in self._do_perfil(contexto) if POR_CODIGO[f.codigo].de_paciente)
        if not unicos or not fontes:
            return {paciente_id: [] for paciente_id in unicos}

        def operacao(uow: UnidadeDeTrabalho) -> list[ItemPendencia]:
            return [item for fonte in fontes for item in fonte.listar_por_pacientes(uow, contexto, unicos)]

        return regras.por_paciente(regras.filtrar(self._executar(operacao), contexto.perfil), unicos)
