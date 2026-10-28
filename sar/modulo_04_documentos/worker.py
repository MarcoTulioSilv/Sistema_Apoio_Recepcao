"""Consumidor da fila de ingestão (DD-33, DD-63): etapas 3 a 6 da §8.3, expiração (DD-34) e limpeza da quarentena.

Uma ingestão por vez. A tomada da fila é uma transação curta (SKIP LOCKED, estado "em processamento"); o
processamento roda fora de transação e grava só na quarentena; o resultado volta ao banco noutra transação. Se o
worker morrer no meio, `retomar` devolve à fila o que ficou em processamento, e tudo recomeça na etapa 3 (§8.4).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_04_documentos.antimalware import Antimalware, AntimalwareIndisponivel, assinaturas_vencidas
from sar.modulo_04_documentos.armazenamento import Quarentena, hash_das_paginas, sha256
from sar.modulo_04_documentos.contrato import FINAIS, CampoCandidato, EstadoIngestao
from sar.modulo_04_documentos.ingestao import RECONSTRUIDO, cifrar_campos, paginas_recebidas
from sar.modulo_04_documentos.isolamento import Resultado, executar
from sar.modulo_04_documentos.processamento import Limites, Recusa
from sar.modulo_08_dados.interfaces.documentos import IngestaoGravada, RepositorioDocumentos
from sar.nucleo.contexto import Contexto
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import Cifra, Relogio
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

log = logging.getLogger(__name__)

PROCESSAR = "documento.ingestao.processar"
EXPIRAR = "documento.ingestao.expirar"
INTERVALO_FILA = 2.0  # DD-63
RECARGA_ESPERA = timedelta(minutes=2)  # DD-99: tempo para o clamd terminar de ler a base nova
RECARGA_INTERVALO = timedelta(hours=1)  # DD-99: nova tentativa de recarga, se a base continuar vencida
INTERVALO_EXPIRACAO = 60.0

Processar = Callable[[Sequence[bytes], str, Sequence[str], Limites, bool, float], Resultado]


def _processar_isolado(
    arquivos: Sequence[bytes], origem: str, campos: Sequence[str], limites: Limites, extrair: bool, tempo: float
) -> Resultado:
    return executar(arquivos, origem, campos, limites, extrair, tempo)


@dataclass(frozen=True, slots=True)
class _Tomada:
    ingestao: IngestaoGravada
    campos: tuple[str, ...]


class ProcessadorIngestoes:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        parametros: LeitorParametros,
        quarentena: Quarentena,
        antimalware: Antimalware,
        cifra: Cifra,
        relogio: Relogio,
        processar: Processar = _processar_isolado,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._parametros = parametros
        self._quarentena = quarentena
        self._antimalware = antimalware
        self._cifra = cifra
        self._relogio = relogio
        self._processar = processar
        self._recarga_em: datetime | None = None  # quando o worker pediu a última recarga ao clamd (DD-99)

    def _contexto(self) -> Contexto:
        return Contexto.sistema("worker.ingestao", self._relogio.agora())

    def _inteiro(self, nome: str) -> int:
        valor = self._parametros.valor(nome)
        if not isinstance(valor, int) or isinstance(valor, bool):
            raise RuntimeError(f"parâmetro {nome} sem valor inteiro")
        return valor

    # ---------------------------------------------------------------- fila
    def retomar(self) -> int:
        """Na subida do worker: o que ficou em processamento volta à fila (§8.4)."""

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repo = uow.repositorio(RepositorioDocumentos)
            presas = repo.em_estado(["em_processamento"])
            for ingestao in presas:
                repo.salvar_ingestao(replace(ingestao, estado="recebida", atualizada_em=self._relogio.agora()))
            return len(presas)

        return self._executar(operacao)

    def _tomar(self) -> _Tomada | None:
        def operacao(uow: UnidadeDeTrabalho) -> _Tomada | None:
            repo = uow.repositorio(RepositorioDocumentos)
            ingestao = repo.tomar_da_fila()
            if ingestao is None:
                return None
            tipo = repo.tipo(ingestao.tipo)
            em_processamento = replace(ingestao, estado="em_processamento", atualizada_em=self._relogio.agora())
            repo.salvar_ingestao(em_processamento)
            return _Tomada(em_processamento, tipo.campos_extracao if tipo is not None else ())

        return self._executar(operacao)

    def processar_proxima(self) -> bool:
        """Processa a próxima da fila. False se a fila está vazia ou se o antimalware está fora do ar (DD-95): nos
        dois casos, o laço espera antes de tentar de novo."""
        tomada = self._tomar()
        if tomada is None:
            return False
        ingestao = tomada.ingestao
        try:
            return self._etapas(ingestao, tomada.campos)
        except Exception as erro:
            # Erro inesperado nosso (não do arquivo): a ingestão volta à fila e o laço segue; só o tipo vai ao log.
            log.error("ingestao.processamento.falhou", extra=campos_do_erro(erro))
            self._devolver(ingestao)
            return False

    def _etapas(self, ingestao: IngestaoGravada, campos: tuple[str, ...]) -> bool:
        nomes = paginas_recebidas(self._quarentena, ingestao.id)
        arquivos = [self._quarentena.ler(ingestao.id, nome) for nome in nomes]
        if hash_das_paginas([sha256(a) for a in arquivos]) != ingestao.hash_entrada:  # SEG-27
            self._rejeitar(ingestao, "hash.divergente")
            return True
        # Etapa 4 antes da 3 no tempo, sem mudar o desfecho: a detecção prevalece (DD-96), e com o clamd fora do ar
        # nem vale a pena processar (DD-95).
        try:
            versao = self._antimalware.versao()
            if assinaturas_vencidas(versao, self._relogio.agora(), self._inteiro("antimalware_idade_maxima")):
                if self._esperar_recarga():
                    self._devolver(ingestao)
                    return False
                self._rejeitar(ingestao, "antimalware.assinaturas_vencidas")
                return True
            self._recarga_em = None
            deteccoes = [d for d in (self._antimalware.varrer(a) for a in arquivos) if d is not None]
        except AntimalwareIndisponivel:
            log.warning("ingestao.antimalware.indisponivel")
            self._devolver(ingestao)
            return False
        if deteccoes:
            self._rejeitar(ingestao, "malware.detectado", detalhe=deteccoes[0])
            return True
        limites = Limites(self._inteiro("pixels_por_pagina") * 1_000_000, self._inteiro("paginas_por_ingestao"))
        extrair = self._parametros.valor("extracao_ligada") is True
        tempo = float(self._inteiro("processamento_tempo_maximo") * max(len(arquivos), 1))
        try:
            resultado = self._processar(arquivos, ingestao.origem, campos, limites, extrair, tempo)
        except Recusa as recusa:
            self._rejeitar(ingestao, recusa.codigo)
            return True
        hash_reconstruido = self._quarentena.gravar(ingestao.id, RECONSTRUIDO, resultado.conteudo)
        candidatos = [CampoCandidato(c.nome, c.valor, c.confianca) for c in resultado.campos]
        self._concluir(ingestao, hash_reconstruido, resultado.paginas, cifrar_campos(self._cifra, ingestao.id,
                                                                                      candidatos))  # fmt: skip
        return True

    def _esperar_recarga(self) -> bool:
        """Base vencida (DD-99): o atualizador pode ter baixado a nova sem o clamd perceber, como quando os dois sobem
        juntos. Pede a recarga e espera um pouco com a ingestão na fila; só recusa se a base continuar vencida depois
        disso. Uma nova recarga é pedida a cada hora, enquanto a base estiver vencida."""
        agora = self._relogio.agora()
        if self._recarga_em is None or agora - self._recarga_em >= RECARGA_INTERVALO:
            self._recarga_em = agora
            log.warning("ingestao.antimalware.recarga_pedida")
            self._antimalware.recarregar()  # AntimalwareIndisponivel: a ingestão volta à fila (DD-95)
            return True
        return agora - self._recarga_em < RECARGA_ESPERA

    def _em_processamento(self, uow: UnidadeDeTrabalho, ingestao: IngestaoGravada) -> IngestaoGravada | None:
        atual = uow.repositorio(RepositorioDocumentos).ingestao(ingestao.id, travar=True)
        return atual if atual is not None and atual.estado == "em_processamento" else None

    def _devolver(self, ingestao: IngestaoGravada) -> None:
        def operacao(uow: UnidadeDeTrabalho) -> None:
            atual = self._em_processamento(uow, ingestao)
            if atual is not None:
                uow.repositorio(RepositorioDocumentos).salvar_ingestao(
                    replace(atual, estado="recebida", atualizada_em=self._relogio.agora())
                )

        self._executar(operacao)

    def _concluir(self, ingestao: IngestaoGravada, hash_reconstruido: str, paginas: int, campos: bytes | None) -> None:
        def operacao(uow: UnidadeDeTrabalho) -> None:
            atual = self._em_processamento(uow, ingestao)
            if atual is None:
                return
            uow.repositorio(RepositorioDocumentos).salvar_ingestao(
                replace(atual, estado="aguardando_conferencia", hash_reconstruido=hash_reconstruido, paginas=paginas,
                        campos_candidatos_cifrados=campos, atualizada_em=self._relogio.agora())
            )  # fmt: skip
            self._auditoria.registrar(uow, self._contexto(), PROCESSAR, "ingestao", ingestao.id.hex(),
                                      {"estado": ("em_processamento", "aguardando_conferencia")})  # fmt: skip

        self._executar(operacao)

    def _rejeitar(self, ingestao: IngestaoGravada, motivo: str, detalhe: str | None = None) -> None:
        """Encerra com o motivo e apaga a quarentena (SEG-12). A assinatura detectada vai só à trilha (SEG-24)."""

        def operacao(uow: UnidadeDeTrabalho) -> None:
            atual = self._em_processamento(uow, ingestao)
            if atual is None:
                return
            uow.repositorio(RepositorioDocumentos).salvar_ingestao(
                replace(atual, estado="rejeitada", motivo_rejeicao=motivo, campos_candidatos_cifrados=None,
                        atualizada_em=self._relogio.agora())
            )  # fmt: skip
            texto = motivo if detalhe is None else f"{motivo}: {detalhe}"
            self._auditoria.registrar(uow, self._contexto(), PROCESSAR, "ingestao", ingestao.id.hex(),
                                      {"estado": ("em_processamento", "rejeitada")}, motivo=texto[:300])  # fmt: skip
            uow.depois_do_commit(lambda: self._quarentena.apagar(ingestao.id))

        self._executar(operacao)

    # ---------------------------------------------------------------- expiração (DD-34) e limpeza
    def expirar(self) -> int:
        """A aberta cujo token venceu; a recebida e a que espera conferência há mais que o prazo da quarentena."""
        agora = self._relogio.agora()
        token = agora - timedelta(minutes=self._inteiro("captura_token_validade"))
        prazo = agora - timedelta(hours=self._inteiro("quarentena_prazo"))

        def operacao(uow: UnidadeDeTrabalho) -> list[bytes]:
            repo = uow.repositorio(RepositorioDocumentos)
            vencidas = repo.criadas_antes(["aberta"], token) + repo.criadas_antes(
                ["recebida", "aguardando_conferencia"], prazo
            )
            contexto = self._contexto()
            for ingestao in vencidas:
                repo.salvar_ingestao(replace(ingestao, estado="expirada", token_hash=None,
                                             campos_candidatos_cifrados=None, atualizada_em=agora))  # fmt: skip
                self._auditoria.registrar(uow, contexto, EXPIRAR, "ingestao", ingestao.id.hex(),
                                          {"estado": (ingestao.estado, "expirada")})  # fmt: skip
            return [i.id for i in vencidas]

        expiradas = self._executar(operacao)
        for ingestao_id in expiradas:
            self._quarentena.apagar(ingestao_id)
        return len(expiradas)

    def limpar_quarentena(self) -> int:
        """Pastas de ingestão encerrada ou inexistente que sobraram (queda entre o commit e a remoção)."""
        presentes = self._quarentena.ingestoes()
        estados = self._executar(lambda uow: uow.repositorio(RepositorioDocumentos).ids_de_ingestoes(presentes))
        sobras = [i for i in presentes if i not in estados or EstadoIngestao(estados[i]) in FINAIS]
        for ingestao_id in sobras:
            self._quarentena.apagar(ingestao_id)
        return len(sobras)

    # ---------------------------------------------------------------- laço (DD-63)
    def rodar(self, parar: threading.Event, intervalo: float = INTERVALO_FILA) -> None:
        self.retomar()
        proxima_expiracao = 0.0
        while not parar.is_set():
            if time.monotonic() >= proxima_expiracao:
                try:
                    self.expirar()
                    self.limpar_quarentena()
                except Exception as erro:
                    log.error("ingestao.expiracao.falhou", extra=campos_do_erro(erro))
                proxima_expiracao = time.monotonic() + INTERVALO_EXPIRACAO
            try:
                trabalhou = self.processar_proxima()
            except Exception as erro:
                log.error("ingestao.fila.falhou", extra=campos_do_erro(erro))
                trabalhou = False
            if not trabalhou:
                parar.wait(intervalo)
