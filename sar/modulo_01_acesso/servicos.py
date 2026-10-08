"""Serviços do MOD-01 (DDS §5)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from sar.modulo_01_acesso.contrato import (
    AuditService,
    AvisoDiagnostico,
    AvisoSimples,
    CodigoIntegridade,
    Conferencia,
    PermissionGuard,
    ResultadoVerificacao,
)
from sar.modulo_01_acesso.regras import cinco_anos_antes, codigo_do_hash, normalizar_codigo, verificar_elos
from sar.modulo_08_dados.canonico import HASH_INICIAL, serializar_alteracoes
from sar.modulo_08_dados.interfaces.trilha import RepositorioExpurgo, RepositorioTrilha
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.eventos import CadeiaDivergente
from sar.nucleo.portas import Relogio
from sar.nucleo.uow import ExecutorDeOperacao, RegistroAuditoria, UnidadeDeTrabalho

# Tamanhos das colunas da tabela auditoria (0001): estourar é erro de programação, não de usuário.
_LIMITES = {"operacao": 80, "entidade": 60, "entidade_id": 40, "motivo": 500, "origem": 45}


GUARDA = PermissionGuard()


def _executor(executar: ExecutorDeOperacao | None, nome: str) -> ExecutorDeOperacao:
    if executar is None:
        raise RuntimeError(f"executor de {nome} não configurado na composição")
    return executar


class ServicoAuditoria:
    def __init__(
        self, executar: ExecutorDeOperacao | None = None, executar_expurgo: ExecutorDeOperacao | None = None
    ) -> None:
        self._executar = executar
        self._executar_expurgo = executar_expurgo

    def registrar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        operacao: str,
        entidade: str,
        entidade_id: str | None,
        alteracoes: Mapping[str, tuple[object, object]] | None = None,
        motivo: str | None = None,
        autorizador_id: int | None = None,
    ) -> None:
        textos = {
            "operacao": operacao,
            "entidade": entidade,
            "entidade_id": entidade_id,
            "motivo": motivo,
            "origem": contexto.origem,
        }
        for campo, valor in textos.items():
            if valor is not None and len(valor) > _LIMITES[campo]:
                raise ValueError(f"{campo} maior que {_LIMITES[campo]} caracteres")
        if not operacao or not entidade:
            raise ValueError("operação e entidade são obrigatórias")
        mudancas = {campo: par for campo, par in (alteracoes or {}).items() if par[0] != par[1]}  # DD-10
        serializar_alteracoes(mudancas)  # recusa agora, e não no commit, valor sem forma canônica
        uow.auditar(
            RegistroAuditoria(
                contexto=contexto,
                operacao=operacao,
                entidade=entidade,
                entidade_id=entidade_id,
                alteracoes=mudancas or None,
                motivo=motivo,
                autorizador_id=autorizador_id,
            )
        )

    def verificar_cadeia(self, contexto: Contexto) -> ResultadoVerificacao:
        GUARDA.exigir(contexto, "acesso.cadeia.verificar")

        def operacao(uow: UnidadeDeTrabalho) -> ResultadoVerificacao:
            trilha = uow.repositorio(RepositorioTrilha)
            cabeca = trilha.cabeca()  # só até aqui: o que for gravado durante a verificação fica para a próxima
            corte = trilha.ultimo_corte()
            primeiro, inicial = (corte.primeiro_id_remanescente, corte.hash_anterior) if corte else (1, HASH_INICIAL)
            resultado = verificar_elos(
                trilha.elos(primeiro, cabeca.ultimo_id),
                primeiro_id=primeiro,
                hash_inicial=inicial,
                cabeca=cabeca,
                ancoras=trilha.ancoras(primeiro),
            )
            if not resultado.integra and resultado.primeiro_divergente_id is not None:
                uow.publicar(CadeiaDivergente(registro_divergente_id=resultado.primeiro_divergente_id))
            elif cabeca.ultimo_id >= primeiro:
                trilha.registrar_ancora(cabeca.ultimo_id, cabeca.ultimo_hash, contexto.instante)  # §13.1
            self.registrar(
                uow,
                contexto,
                "acesso.cadeia.verificar",
                "auditoria",
                None,
                {
                    "resultado": (None, "integra" if resultado.integra else "divergente"),
                    "verificados": (None, resultado.verificados),
                },
            )
            return resultado

        return _executor(self._executar, "operação")(operacao)

    def codigo_vigente(self, uow: UnidadeDeTrabalho) -> CodigoIntegridade | None:
        ancora = uow.repositorio(RepositorioTrilha).ancora_mais_recente()
        if ancora is None:
            return None
        return CodigoIntegridade(ancora.ate_registro_id, codigo_do_hash(ancora.hash), ancora.registrada_em)

    def expurgar(self, contexto: Contexto) -> int:
        GUARDA.exigir(contexto, "acesso.trilha.expurgar")
        limite = cinco_anos_antes(contexto.instante)  # DEC-45

        def operacao(uow: UnidadeDeTrabalho) -> int:
            expurgo = uow.repositorio(RepositorioExpurgo)
            ultimo = expurgo.ultimo_elo_antes_de(limite)
            if ultimo is None:
                return 0
            ultimo_id, ultimo_hash = ultimo
            quantidade = expurgo.contar_ate(ultimo_id)
            # O corte guarda o hash do último elo apagado: a verificação recomeça dele (RNF-628).
            expurgo.registrar_corte(ultimo_id + 1, ultimo_hash, contexto.instante, quantidade)
            expurgo.apagar_ate(ultimo_id)
            return quantidade

        return _executor(self._executar_expurgo, "expurgo")(operacao)


def manipulador_aviso_integridade(relogio: Relogio) -> Callable[[UnidadeDeTrabalho, CadeiaDivergente], None]:
    """Consumidor de CadeiaDivergente (DDS §3.11): abre um aviso por elo divergente, sem repetir (RF-1011)."""

    def abrir(uow: UnidadeDeTrabalho, evento: CadeiaDivergente) -> None:
        trilha = uow.repositorio(RepositorioTrilha)
        if any(a.registro_divergente_id == evento.registro_divergente_id for a in trilha.avisos_abertos()):
            return
        trilha.abrir_aviso(evento.registro_divergente_id, relogio.agora())

    return abrir


class ServicoIntegridade:
    def __init__(self, executar: ExecutorDeOperacao, auditoria: AuditService) -> None:
        self._executar = executar
        self._auditoria = auditoria

    def ver_avisos(self, contexto: Contexto) -> list[AvisoSimples]:
        celula = GUARDA.exigir(contexto, "acesso.aviso_integridade.ver")

        def operacao(uow: UnidadeDeTrabalho) -> list[AvisoSimples]:
            avisos = uow.repositorio(RepositorioTrilha).avisos_abertos()
            self._auditoria.registrar(uow, contexto, "acesso.aviso_integridade.ver", "aviso_integridade", None)
            if celula.nota == "diagnóstico":  # TI; a administração vê a versão "simples" (RF-1011)
                return [AvisoDiagnostico(a.id, a.detectado_em, a.registro_divergente_id) for a in avisos]
            return [AvisoSimples(a.id, a.detectado_em) for a in avisos]

        return self._executar(operacao)

    def encerrar_aviso(self, contexto: Contexto, aviso_id: int, explicacao: str) -> None:
        GUARDA.exigir(contexto, "acesso.aviso_integridade.encerrar")
        texto = explicacao.strip()
        if not texto:
            raise RegraViolada("aviso.explicacao_obrigatoria")  # DEC-43
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise AcessoNegado()

        def operacao(uow: UnidadeDeTrabalho) -> None:
            trilha = uow.repositorio(RepositorioTrilha)
            aviso = trilha.aviso(aviso_id)
            if aviso is None:
                raise NaoEncontrado()
            if aviso.encerrado_em is not None:
                raise RegraViolada("aviso.ja_encerrado")
            trilha.encerrar_aviso(aviso_id, usuario_id, contexto.instante, texto)
            self._auditoria.registrar(
                uow,
                contexto,
                "acesso.aviso_integridade.encerrar",
                "aviso_integridade",
                str(aviso_id),
                {"encerrado_em": (None, contexto.instante), "explicacao": (None, texto)},
            )

        self._executar(operacao)

    def conferir_codigo(self, contexto: Contexto, registro_id: int, codigo: str) -> Conferencia:
        GUARDA.exigir(contexto, "acesso.ancora.conferir")
        procurado = normalizar_codigo(codigo)
        if procurado is None:
            raise RegraViolada("ancora.codigo_invalido")

        def operacao(uow: UnidadeDeTrabalho) -> Conferencia:
            trilha = uow.repositorio(RepositorioTrilha)
            elo, ancora = trilha.elo(registro_id), trilha.ancora_do_registro(registro_id)
            hashes = [h for h in (elo.hash_registro if elo else None, ancora.hash if ancora else None) if h]
            if not hashes:
                resultado = Conferencia.SEM_REGISTRO
            elif all(h.startswith(procurado) for h in hashes):
                resultado = Conferencia.CONFERE
            else:
                resultado = Conferencia.NAO_CONFERE
            self._auditoria.registrar(
                uow,
                contexto,
                "acesso.ancora.conferir",
                "auditoria",
                str(registro_id),
                {"resultado": (None, resultado.value)},
            )
            return resultado

        return self._executar(operacao)
