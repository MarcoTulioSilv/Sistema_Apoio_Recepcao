"""Ingestão (DDS §8.3 e §8.4), do lado da web: abertura com token de uso único, recebimento página a página na
quarentena, conclusão, conferência, incorporação no cofre e rejeição. O processamento (etapas 3 a 6) é do worker.

Na quarentena, cada ingestão tem as páginas recebidas (`p0001`, `p0002`…) e, depois do worker, o documento
reconstruído (`reconstruido`); os campos candidatos esperam a conferência cifrados na própria ingestão (DD-40).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import BinaryIO

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_04_documentos.armazenamento import Cofre, Quarentena, hash_das_paginas, ler_limitado, sha256
from sar.modulo_04_documentos.contrato import (
    MOTIVOS_REJEICAO,
    CampoCandidato,
    Conferencia,
    EstadoIngestao,
    IngestaoAberta,
    SituacaoIngestao,
)
from sar.modulo_08_dados.interfaces.documentos import DocumentoGravado, IngestaoGravada, RepositorioDocumentos
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, IntegridadeViolada, NaoEncontrado, RegraViolada
from sar.nucleo.eventos import DocumentoIncorporado
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import Cifra, Finalidade, Relogio
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
ABRIR = "documento.ingestao.abrir"
CONFERIR = "documento.ingestao.conferir"
INCORPORAR = "documento.ingestao.incorporar"
REJEITAR = "documento.ingestao.rejeitar"
NOVA_VERSAO = "documento.nova_versao"
TAMANHO_MOTIVO = 300
RECONSTRUIDO = "reconstruido"
FOTO_BYTES_MAXIMO = 2 * 1024 * 1024  # teto fixo da §10.1
TAMANHO_NONCE = 12
LOCAL_MAXIMO = 80


def nome_pagina(numero: int) -> str:
    return f"p{numero:04d}"


def paginas_recebidas(quarentena: Quarentena, ingestao_id: bytes) -> list[str]:
    return [n for n in quarentena.nomes(ingestao_id) if n.startswith("p")]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def formato(origem: str) -> str:
    return "jpeg" if origem == "webcam" else "pdf"


# ------------------------------------------------------------------ campos candidatos cifrados (P-18)
def _associado_campos(ingestao_id: bytes) -> bytes:
    return ingestao_id + b"campos"


def cifrar_campos(cifra: Cifra, ingestao_id: bytes, campos: Sequence[CampoCandidato]) -> bytes | None:
    if not campos:
        return None
    claro = json.dumps([[c.nome, c.valor, c.confianca] for c in campos]).encode()
    nonce, cifrado = cifra.cifrar(Finalidade.QUARENTENA, claro, _associado_campos(ingestao_id))
    return nonce + cifrado


def decifrar_campos(cifra: Cifra, ingestao_id: bytes, bruto: bytes | None) -> tuple[CampoCandidato, ...]:
    if bruto is None:
        return ()
    claro = cifra.decifrar(
        Finalidade.QUARENTENA, bruto[:TAMANHO_NONCE], bruto[TAMANHO_NONCE:], _associado_campos(ingestao_id)
    )
    return tuple(CampoCandidato(nome, valor, confianca) for nome, valor, confianca in json.loads(claro))


def id_do_texto(texto: str) -> bytes:
    try:
        valor = bytes.fromhex(texto)
    except ValueError:
        raise NaoEncontrado() from None
    if len(valor) != 16:
        raise NaoEncontrado()
    return valor


def _usuario(contexto: Contexto) -> int:
    if contexto.usuario_id is None:
        raise AcessoNegado()
    return contexto.usuario_id


def situacao_de(ingestao: IngestaoGravada) -> SituacaoIngestao:
    return SituacaoIngestao(ingestao.id.hex(), ingestao.paciente_id, ingestao.tipo, ingestao.origem,
                            EstadoIngestao(ingestao.estado), ingestao.motivo_rejeicao, ingestao.paginas)  # fmt: skip


class ServicoIngestao:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        parametros: LeitorParametros,
        quarentena: Quarentena,
        cofre: Cofre,
        cifra: Cifra,
        relogio: Relogio,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._parametros = parametros
        self._quarentena = quarentena
        self._cofre = cofre
        self._cifra = cifra
        self._relogio = relogio

    def _inteiro(self, nome: str) -> int:
        valor = self._parametros.valor(nome)
        if not isinstance(valor, int) or isinstance(valor, bool):
            raise RuntimeError(f"parâmetro {nome} sem valor inteiro")
        return valor

    # ---------------------------------------------------------------- etapa 1
    def abrir(
        self,
        contexto: Contexto,
        paciente_id: int,
        tipo: str,
        origem: str,
        vinculo: str | None = None,
        substitui_id: str | None = None,
        motivo: str | None = None,
    ) -> IngestaoAberta:
        GUARDA.exigir(contexto, ABRIR)
        autor = _usuario(contexto)
        substituida = id_do_texto(substitui_id) if substitui_id is not None else None
        motivo = (motivo or "").strip()
        if substituida is not None:
            GUARDA.exigir(contexto, NOVA_VERSAO)
            if not motivo or len(motivo) > TAMANHO_MOTIVO:
                raise RegraViolada("versao.motivo")  # correção só por nova versão, com motivo (RF-708)
        token = secrets.token_urlsafe(32)  # DD-05
        ingestao_id = uuid.uuid4().bytes  # nome aleatório da pasta na quarentena (SEG-07)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repo = uow.repositorio(RepositorioDocumentos)
            tipo_gravado = repo.tipo(tipo)
            if tipo_gravado is None:
                raise RegraViolada("tipo.inexistente")
            if tipo_gravado.origem != origem:
                raise RegraViolada("tipo.origem")
            if not repo.paciente_ativo(paciente_id):
                raise RegraViolada("paciente.anulado")
            if substituida is not None:
                self._conferir_substituida(repo, substituida, paciente_id, tipo)
            repo.criar_ingestao(
                IngestaoGravada(
                    ingestao_id, paciente_id, tipo, tipo_gravado.origem, vinculo, substituida, "aberta", None,
                    hash_token(token), None, None, None, None, None, contexto.instante, autor, contexto.instante,
                )
            )  # fmt: skip
            self._auditoria.registrar(uow, contexto, ABRIR, "ingestao", ingestao_id.hex(),
                                      {"tipo": (None, tipo), "paciente_id": (None, paciente_id)})  # fmt: skip
            if substituida is not None:
                self._auditoria.registrar(uow, contexto, NOVA_VERSAO, "documento", substituida.hex(),
                                          {"ingestao": (None, ingestao_id.hex())}, motivo=motivo)  # fmt: skip

        self._executar(operacao)
        return IngestaoAberta(ingestao_id.hex(), token)

    @staticmethod
    def _conferir_substituida(repo: RepositorioDocumentos, documento_id: bytes, paciente_id: int, tipo: str) -> None:
        """Só a versão vigente, do mesmo paciente e tipo, ainda não descartada, pode ser substituída (RF-708)."""
        anterior = repo.documento(documento_id)
        if (
            anterior is None
            or anterior.paciente_id != paciente_id
            or anterior.tipo != tipo
            or anterior.descartado_em is not None
            or repo.sucessor(documento_id) is not None
        ):
            raise RegraViolada("versao.substituida")

    # ---------------------------------------------------------------- etapa 2
    def _pelo_token(self, uow: UnidadeDeTrabalho, ingestao_id: bytes, token: str) -> IngestaoGravada:
        """A ingestão aberta cujo token confere e ainda vale (SEG-01). Qualquer falha é AcessoNegado, sem dizer qual."""
        ingestao = uow.repositorio(RepositorioDocumentos).ingestao(ingestao_id, travar=True)
        if ingestao is None or ingestao.estado != "aberta" or ingestao.token_hash is None:
            raise AcessoNegado()
        if not hmac.compare_digest(ingestao.token_hash, hash_token(token)):
            raise AcessoNegado()
        validade = timedelta(minutes=self._inteiro("captura_token_validade"))
        if self._relogio.agora() > ingestao.criada_em + validade:
            raise AcessoNegado()
        return ingestao

    def receber_pagina(self, ingestao_id: str, token: str, numero: int, fluxo: BinaryIO) -> None:
        id_ = id_do_texto(ingestao_id)
        ingestao = self._executar(lambda uow: self._pelo_token(uow, id_, token))
        maximo_paginas = 1 if ingestao.origem == "webcam" else self._inteiro("paginas_por_ingestao")
        if not 1 <= numero <= maximo_paginas:
            raise RegraViolada("pagina.numero")
        limite = FOTO_BYTES_MAXIMO if ingestao.origem == "webcam" else self._inteiro("pagina_tamanho_maximo") << 20
        conteudo = ler_limitado(fluxo, limite)  # SEG-06: para no limite, sem guardar o excesso
        if not conteudo:
            raise RegraViolada("arquivo.vazio")
        self._quarentena.gravar(id_, nome_pagina(numero), conteudo)  # cifrado (SEG-08)

    def concluir(self, ingestao_id: str, token: str, paginas: int) -> None:
        id_ = id_do_texto(ingestao_id)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            ingestao = self._pelo_token(uow, id_, token)
            esperadas = [nome_pagina(n) for n in range(1, paginas + 1)]
            if paginas < 1 or paginas_recebidas(self._quarentena, id_) != esperadas:
                raise RegraViolada("paginas.faltando")
            hashes = [sha256(self._quarentena.ler(id_, nome)) for nome in esperadas]
            uow.repositorio(RepositorioDocumentos).salvar_ingestao(
                replace(ingestao, estado="recebida", token_hash=None, hash_entrada=hash_das_paginas(hashes),
                        paginas=paginas, atualizada_em=self._relogio.agora())
            )  # fmt: skip

        self._executar(operacao)

    def cancelar(self, contexto: Contexto, ingestao_id: str) -> None:
        GUARDA.exigir(contexto, ABRIR)
        id_ = id_do_texto(ingestao_id)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repo = uow.repositorio(RepositorioDocumentos)
            ingestao = repo.ingestao(id_, travar=True)
            if ingestao is None:
                raise NaoEncontrado()
            if ingestao.estado != "aberta":
                raise RegraViolada("ingestao.estado")
            repo.salvar_ingestao(replace(ingestao, estado="cancelada", token_hash=None,
                                         atualizada_em=contexto.instante))  # fmt: skip
            uow.depois_do_commit(lambda: self._quarentena.apagar(id_))

        self._executar(operacao)

    # ---------------------------------------------------------------- acompanhamento e conferência (etapa 7)
    def situacao(self, contexto: Contexto, ingestao_id: str) -> SituacaoIngestao:
        GUARDA.exigir(contexto, ABRIR)
        id_ = id_do_texto(ingestao_id)

        def operacao(uow: UnidadeDeTrabalho) -> SituacaoIngestao:
            ingestao = uow.repositorio(RepositorioDocumentos).ingestao(id_)
            if ingestao is None:
                raise NaoEncontrado()
            return situacao_de(ingestao)

        return self._executar(operacao)

    @staticmethod
    def _aguardando(uow: UnidadeDeTrabalho, id_: bytes, travar: bool = False) -> IngestaoGravada:
        ingestao = uow.repositorio(RepositorioDocumentos).ingestao(id_, travar=travar)
        if ingestao is None:
            raise NaoEncontrado()
        if ingestao.estado != "aguardando_conferencia":
            raise RegraViolada("ingestao.estado")
        return ingestao

    def conferir(self, contexto: Contexto, ingestao_id: str) -> Conferencia:
        GUARDA.exigir(contexto, CONFERIR)
        id_ = id_do_texto(ingestao_id)

        def operacao(uow: UnidadeDeTrabalho) -> Conferencia:
            ingestao = self._aguardando(uow, id_)
            self._auditoria.registrar(uow, contexto, CONFERIR, "ingestao", id_.hex())
            campos = decifrar_campos(self._cifra, id_, ingestao.campos_candidatos_cifrados)
            return Conferencia(situacao_de(ingestao), campos, ingestao.vinculo)

        return self._executar(operacao)

    def _reconstruido(self, ingestao: IngestaoGravada) -> bytes:
        """O documento do worker, conferido pelo hash que ele gravou (SEG-27)."""
        conteudo = self._quarentena.ler(ingestao.id, RECONSTRUIDO)
        if ingestao.hash_reconstruido is None or sha256(conteudo) != ingestao.hash_reconstruido:
            raise IntegridadeViolada("documento reconstruído não confere")
        return conteudo

    def pagina_em_conferencia(self, contexto: Contexto, ingestao_id: str) -> tuple[bytes, str]:
        GUARDA.exigir(contexto, CONFERIR)
        id_ = id_do_texto(ingestao_id)
        ingestao = self._executar(lambda uow: self._aguardando(uow, id_))
        return self._reconstruido(ingestao), formato(ingestao.origem)

    # ---------------------------------------------------------------- etapa 8
    def incorporar(self, contexto: Contexto, ingestao_id: str) -> str:
        GUARDA.exigir(contexto, INCORPORAR)
        _usuario(contexto)
        id_ = id_do_texto(ingestao_id)

        def operacao(uow: UnidadeDeTrabalho) -> str:
            repo = uow.repositorio(RepositorioDocumentos)
            ingestao = self._aguardando(uow, id_, travar=True)
            if not repo.paciente_ativo(ingestao.paciente_id):
                raise RegraViolada("paciente.anulado")
            versao = 1
            if ingestao.substitui_id is not None:
                self._conferir_substituida(repo, ingestao.substitui_id, ingestao.paciente_id, ingestao.tipo)
                anterior = repo.documento(ingestao.substitui_id)
                versao = anterior.versao + 1 if anterior is not None else 1
            conteudo = self._reconstruido(ingestao)
            if repo.documento_com_hash(sha256(conteudo)) is not None:
                raise RegraViolada("documento.repetido")  # o mesmo conteúdo já está no cofre (hash único, §8.7)
            documento_id = uuid.uuid4().bytes
            guardado = self._cofre.guardar(documento_id, conteudo)  # fase do arquivo (DD-37)
            repo.criar_documento(
                DocumentoGravado(
                    documento_id, ingestao.paciente_id, ingestao.tipo, versao, ingestao.substitui_id, guardado.arquivo,
                    guardado.chave_cifrada, guardado.nonce, guardado.hash_sha256, ingestao.paginas or 1,
                    ingestao.origem, ingestao.criada_em, ingestao.criada_por, contexto.origem[:LOCAL_MAXIMO], None,
                    None, None,
                )
            )  # fmt: skip
            repo.salvar_ingestao(replace(ingestao, estado="incorporada", campos_candidatos_cifrados=None,
                                         documento_id=documento_id, atualizada_em=contexto.instante))  # fmt: skip
            alteracoes: dict[str, tuple[object, object]] = {
                "tipo": (None, ingestao.tipo), "versao": (None, versao), "hash_sha256": (None, guardado.hash_sha256),
                "ingestao": (None, id_.hex()),
            }  # fmt: skip
            self._auditoria.registrar(uow, contexto, INCORPORAR, "documento", documento_id.hex(), alteracoes)
            uow.publicar(DocumentoIncorporado(documento_id, ingestao.paciente_id, ingestao.tipo, ingestao.vinculo))
            uow.depois_do_commit(lambda: self._quarentena.apagar(id_))
            return documento_id.hex()

        return self._executar(operacao)

    def rejeitar(self, contexto: Contexto, ingestao_id: str, motivo: str) -> None:
        GUARDA.exigir(contexto, REJEITAR)
        if motivo not in MOTIVOS_REJEICAO:
            raise RegraViolada("ingestao.motivo")
        id_ = id_do_texto(ingestao_id)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            ingestao = self._aguardando(uow, id_, travar=True)
            uow.repositorio(RepositorioDocumentos).salvar_ingestao(
                replace(ingestao, estado="rejeitada", motivo_rejeicao=f"conferencia.{motivo}",
                        campos_candidatos_cifrados=None, atualizada_em=contexto.instante)
            )  # fmt: skip
            self._auditoria.registrar(uow, contexto, REJEITAR, "ingestao", id_.hex(), motivo=motivo)
            uow.depois_do_commit(lambda: self._quarentena.apagar(id_))

        self._executar(operacao)
