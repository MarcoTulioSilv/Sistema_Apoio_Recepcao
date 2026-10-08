"""Serviços do MOD-06 (DDS §10): leitura e alteração dos parâmetros declarados no núcleo (DD-48, DD-73)."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_06_configuracao.contrato import ParametroVigente, Valor
from sar.modulo_06_configuracao.regras import de_texto, para_texto, validar
from sar.modulo_08_dados.interfaces.parametros import RepositorioParametro, ValorGravado
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada
from sar.nucleo.parametros import PARAMETROS, Parametro, VerificadorUso
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

log = logging.getLogger(__name__)
GUARDA = PermissionGuard()

# Condição da linha config.parametro.alterar no DDS §4.6, pelo perfil que edita o parâmetro.
_CONDICAO = {Perfil.ADMINISTRACAO: "operacionais", Perfil.TI: "técnicos"}


def _declarado(nome: str) -> Parametro:
    parametro = PARAMETROS.get(nome)
    if parametro is None:
        raise LookupError(f"parâmetro não declarado no núcleo: {nome}")  # DD-48: o que não é declarado não existe
    return parametro


def _vigente(parametro: Parametro, gravado: ValorGravado | None) -> Valor:
    """O valor gravado se for válido hoje; senão o padrão, com aviso no log técnico (sem o valor)."""
    if gravado is None:
        return parametro.padrao
    try:
        return de_texto(parametro, gravado.valor)
    except ValueError, RegraViolada:
        log.warning("config.parametro.valor_invalido", extra={"resultado": parametro.nome})
        return parametro.padrao


class LeitorParametrosSQL:
    """Implementa a porta LeitorParametros do núcleo. Cada leitura é uma transação curta: a porta não recebe a
    unidade de trabalho, e a DD-48 pede leitura por operação, sem cache entre processos."""

    def __init__(self, executar: ExecutorDeOperacao) -> None:
        self._executar = executar

    def valor(self, nome: str) -> Valor:
        parametro = _declarado(nome)
        return self._executar(lambda uow: _vigente(parametro, uow.repositorio(RepositorioParametro).valor(nome)))


class ServicoConfiguracao:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        verificadores_uso: Mapping[str, VerificadorUso] | None = None,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._verificadores = dict(verificadores_uso or {})

    def listar_parametros(self, contexto: Contexto) -> list[ParametroVigente]:
        GUARDA.exigir(contexto, "config.consultar")

        def operacao(uow: UnidadeDeTrabalho) -> list[ParametroVigente]:
            gravados = {g.nome: g for g in uow.repositorio(RepositorioParametro).todos()}
            vigentes = []
            for nome in sorted(PARAMETROS):
                p, g = PARAMETROS[nome], gravados.get(nome)
                vigentes.append(
                    ParametroVigente(
                        nome=nome,
                        unidade=p.unidade.value,
                        valor=_vigente(p, g),
                        padrao=p.padrao,
                        minimo=p.minimo,
                        maximo=p.maximo,
                        editor=p.editor,
                        imutavel_apos_uso=p.imutavel_apos_uso,
                        alterado_em=g.alterado_em if g else None,
                        alterado_por=g.alterado_por if g else None,
                    )
                )
            return vigentes

        return self._executar(operacao)

    def alterar_parametro(self, contexto: Contexto, nome: str, valor: Valor) -> None:
        parametro = _declarado(nome)
        GUARDA.exigir(contexto, "config.parametro.alterar", _CONDICAO[parametro.editor])
        novo = validar(parametro, valor)
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise AcessoNegado()

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioParametro)
            atual = _vigente(parametro, repositorio.valor(nome))
            if atual == novo:
                return  # nada muda, nada é gravado nem auditado (DD-10)
            verificador = self._verificadores.get(nome)
            if parametro.imutavel_apos_uso and verificador is not None and verificador.em_uso(uow):
                raise RegraViolada("parametro.imutavel", {"nome": nome})  # DD-51
            repositorio.gravar(nome, para_texto(parametro, novo), contexto.instante, usuario_id)
            self._auditoria.registrar(
                uow, contexto, "config.parametro.alterar", "parametro", nome, {"valor": (atual, novo)}
            )

        self._executar(operacao)
