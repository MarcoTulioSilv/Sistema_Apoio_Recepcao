"""Rascunho de cadastro (DDS §6.6, RF-919, RF-920, DD-07): o destino do preenchimento sem o mínimo da P-03 e o
salvamento automático da tela. Um por usuário, só dele, cifrado com a finalidade `rascunhos` e o id do rascunho
como dado associado. Nenhuma regra do cadastro roda aqui (unicidade, dígito, tríade): todas rodam quando o
rascunho vira paciente. O descarte dos vencidos é o job do Incremento 6."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import RascunhoSalvo
from sar.modulo_02_cadastro.servicos import hoje_na_clinica
from sar.modulo_08_dados.interfaces.rascunhos import RascunhoGravado, RepositorioRascunho
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, RegraViolada
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import Cifra, Finalidade, ItemPendencia, Prioridade
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
ENTIDADE = "rascunho_cadastro"
MAXIMO_CAMPOS = 200
MAXIMO_CHAVE = 60
MAXIMO_VALOR = 500


def _usuario(contexto: Contexto) -> int:
    if contexto.usuario_id is None:
        raise AcessoNegado()  # rascunho é de uma pessoa (§4, "próprio")
    return contexto.usuario_id


def validar_conteudo(conteudo: Mapping[str, str]) -> dict[str, str]:
    """Texto do formulário, campo a campo, com limites que bastam à ficha inteira."""
    if len(conteudo) > MAXIMO_CAMPOS or any(
        not isinstance(k, str) or not isinstance(v, str) or len(k) > MAXIMO_CHAVE or len(v) > MAXIMO_VALOR
        for k, v in conteudo.items()
    ):
        raise RegraViolada("rascunho.conteudo")
    return dict(conteudo)


def _associado(rascunho_id: int) -> bytes:
    return str(rascunho_id).encode()


def _texto(conteudo: Mapping[str, str]) -> bytes:
    return json.dumps(conteudo, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class ServicoRascunhos:
    """Implementa o RascunhoService do contrato."""

    def __init__(
        self, executar: ExecutorDeOperacao, auditoria: AuditService, cifra: Cifra, parametros: LeitorParametros
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._cifra = cifra
        self._parametros = parametros

    def salvar(self, contexto: Contexto, conteudo: Mapping[str, str]) -> RascunhoSalvo:
        GUARDA.exigir(contexto, "cadastro.rascunho.salvar")
        usuario_id = _usuario(contexto)
        limpo = validar_conteudo(conteudo)
        prazo = self._prazo()

        def operacao(uow: UnidadeDeTrabalho) -> RascunhoSalvo:
            repositorio = uow.repositorio(RepositorioRascunho)
            atual = repositorio.do_usuario(usuario_id)
            if atual is not None and atual.conteudo_cifrado and self._abrir(atual) == limpo:
                return _salvo(limpo, atual.atualizado_em, prazo)  # nada mudou: nada é gravado nem auditado (DD-10)
            rascunho_id = atual.id if atual is not None else repositorio.criar(usuario_id, contexto.instante)
            nonce, cifrado = self._cifra.cifrar(Finalidade.RASCUNHOS, _texto(limpo), _associado(rascunho_id))
            repositorio.gravar(rascunho_id, cifrado, nonce, contexto.instante)
            self._auditoria.registrar(uow, contexto, "cadastro.rascunho.salvar", ENTIDADE, str(rascunho_id))
            return _salvo(limpo, contexto.instante, prazo)

        try:
            return self._executar(operacao)
        except Exception as erro:
            if campos_do_erro(erro).get("restricao") != "uq_rascunho_cadastro__usuario":
                raise
            return self._executar(operacao)  # outra aba criou o rascunho no mesmo instante: agora ele existe

    def retomar(self, contexto: Contexto) -> RascunhoSalvo | None:
        """O rascunho do próprio usuário, se houver e ainda estiver no prazo."""
        GUARDA.exigir(contexto, "cadastro.rascunho.retomar")
        usuario_id = _usuario(contexto)
        prazo = self._prazo()
        hoje = hoje_na_clinica(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> RascunhoSalvo | None:
            atual = uow.repositorio(RepositorioRascunho).do_usuario(usuario_id)
            if atual is None or not atual.conteudo_cifrado:
                return None
            salvo = _salvo(self._abrir(atual), atual.atualizado_em, prazo)
            if hoje > salvo.descarte_em:
                return None  # vencido: o job o elimina (RF-920)
            self._auditoria.registrar(uow, contexto, "cadastro.rascunho.retomar", ENTIDADE, str(atual.id))
            return salvo

        return self._executar(operacao)

    def descartar(self, contexto: Contexto) -> None:
        GUARDA.exigir(contexto, "cadastro.rascunho.descartar")
        usuario_id = _usuario(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioRascunho)
            atual = repositorio.do_usuario(usuario_id)
            if atual is None:
                return
            repositorio.remover_do_usuario(usuario_id)
            self._auditoria.registrar(uow, contexto, "cadastro.rascunho.descartar", ENTIDADE, str(atual.id))

        self._executar(operacao)

    def _abrir(self, rascunho: RascunhoGravado) -> dict[str, str]:
        texto = self._cifra.decifrar(
            Finalidade.RASCUNHOS, rascunho.nonce, rascunho.conteudo_cifrado, _associado(rascunho.id)
        )
        conteudo: dict[str, str] = json.loads(texto)
        return conteudo

    def _prazo(self) -> int:
        valor = self._parametros.valor("rascunho_prazo")
        return valor if isinstance(valor, int) and not isinstance(valor, bool) else 3


def _salvo(conteudo: dict[str, str], atualizado_em: datetime, prazo_dias: int) -> RascunhoSalvo:
    """O descarte é no fim do prazo, contado em dias da clínica a partir do último salvamento (RF-920)."""
    return RascunhoSalvo(
        conteudo, atualizado_em, atualizado_em.astimezone(FUSO_CLINICA).date() + timedelta(days=prazo_dias)
    )


class FonteRascunhoProximoDoDescarte:
    """§11.1, linha 13: rascunho perto do descarte, só para o autor (ERS §3.2.13)."""

    codigo = "rascunho_proximo_descarte"
    prioridade = Prioridade.NORMAL
    PERFIS = frozenset({Perfil.RECEPCAO, Perfil.ADMINISTRACAO})

    def __init__(self, parametros: LeitorParametros) -> None:
        self._parametros = parametros

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        if contexto.perfil not in self.PERFIS or contexto.usuario_id is None:
            return []
        atual = uow.repositorio(RepositorioRascunho).do_usuario(contexto.usuario_id)
        if atual is None or not atual.conteudo_cifrado:
            return []
        prazo, aviso = self._dias("rascunho_prazo", 3), self._dias("rascunho_aviso", 1)
        descarte = atual.atualizado_em.astimezone(FUSO_CLINICA).date() + timedelta(days=prazo)
        if hoje_na_clinica(contexto) < descarte - timedelta(days=aviso):
            return []
        descricao = f"Rascunho de cadastro será descartado em {descarte:%d/%m/%Y}"
        return [ItemPendencia(self.codigo, self.prioridade, atual.atualizado_em, descricao, "/cadastro/novo")]

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        return []  # o rascunho ainda não é paciente

    def _dias(self, nome: str, padrao: int) -> int:
        valor = self._parametros.valor(nome)
        return valor if isinstance(valor, int) and not isinstance(valor, bool) else padrao
