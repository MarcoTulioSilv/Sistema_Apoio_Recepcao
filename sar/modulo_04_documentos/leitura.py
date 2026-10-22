"""Leituras do MOD-04 para outros módulos (DDS §8.8): checklist (MOD-07), retenção, foto do crachá (MOD-05) e cópia
ao titular (MOD-11). As que entregam conteúdo auditam cada documento entregue (RF-710) e conferem o hash (DD-38);
documento bloqueado, descartado ou com hash divergente fica de fora."""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import date, datetime
from functools import partial

import pikepdf
from PIL import Image

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_04_documentos.armazenamento import Cofre
from sar.modulo_04_documentos.contrato import ElegivelDescarte
from sar.modulo_04_documentos.paginas import formato_da_origem
from sar.modulo_04_documentos.retencao import elegiveis
from sar.modulo_08_dados.interfaces.documentos import DocumentoGravado, RepositorioDocumentos
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import IntegridadeViolada
from sar.nucleo.portas import FonteMarcoRetencao
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
VER = "documento.ver"
FOTO = "foto_paciente"


def vigentes_legiveis(repo: RepositorioDocumentos, paciente_id: int) -> list[DocumentoGravado]:
    documentos = repo.do_paciente(paciente_id)
    substituidos = {d.substitui_id for d in documentos if d.substitui_id is not None}
    return [d for d in documentos
            if d.id not in substituidos and d.descartado_em is None and d.bloqueado_em is None]  # fmt: skip


def pagina_da_foto(pdf: pikepdf.Pdf, jpeg: bytes) -> pikepdf.Page:
    """A foto colorida como página do PDF, sem reprocessar: o próprio JPEG em DCTDecode."""
    largura, altura = Image.open(io.BytesIO(jpeg)).size
    imagem = pikepdf.Stream(pdf, jpeg)
    imagem.Type, imagem.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
    imagem.Width, imagem.Height, imagem.BitsPerComponent = largura, altura, 8
    imagem.ColorSpace, imagem.Filter = pikepdf.Name.DeviceRGB, pikepdf.Name.DCTDecode
    pontos_l, pontos_a = largura * 72 / 150, altura * 72 / 150
    conteudo = pikepdf.Stream(pdf, f"q {pontos_l:.2f} 0 0 {pontos_a:.2f} 0 0 cm /Im0 Do Q".encode())
    return pikepdf.Page(pikepdf.Dictionary(
        Type=pikepdf.Name.Page, MediaBox=[0, 0, pontos_l, pontos_a],
        Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=imagem)), Contents=conteudo,
    ))  # fmt: skip


def _bloquear(documento_id: bytes, contexto: Contexto, uow: UnidadeDeTrabalho) -> None:
    uow.repositorio(RepositorioDocumentos).bloquear(documento_id, contexto.instante, "hash_divergente")


class ServicoLeituraDocumentos:
    def __init__(
        self, executar: ExecutorDeOperacao, auditoria: AuditService, cofre: Cofre, marco: FonteMarcoRetencao
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._cofre = cofre
        self._marco = marco

    def tipos_presentes(self, uow: UnidadeDeTrabalho, paciente_ids: Sequence[int]) -> dict[int, set[str]]:
        return uow.repositorio(RepositorioDocumentos).tipos_presentes(paciente_ids)

    def ultimo_documento_em(self, uow: UnidadeDeTrabalho, paciente_id: int) -> datetime | None:
        return uow.repositorio(RepositorioDocumentos).ultimo_documento_em([paciente_id]).get(paciente_id)

    def elegiveis_descarte(self, uow: UnidadeDeTrabalho, hoje: date) -> list[ElegivelDescarte]:
        return [ElegivelDescarte(e.documento_id.hex(), e.paciente_id, e.tipo, e.prazo)
                for e in elegiveis(uow, self._marco, hoje)]  # fmt: skip

    def _entregar(self, contexto: Contexto, documentos: list[DocumentoGravado]) -> list[tuple[DocumentoGravado, bytes]]:
        """Audita a entrega na mesma transação e decifra; o que não confere é bloqueado e fica de fora."""

        def auditar(uow: UnidadeDeTrabalho) -> None:
            for documento in documentos:
                self._auditoria.registrar(uow, contexto, VER, "documento", documento.id.hex())

        self._executar(auditar)
        entregues = []
        for documento in documentos:
            try:
                conteudo = self._cofre.ler(documento.id, documento.arquivo, documento.chave_cifrada or b"",
                                           documento.nonce, documento.hash_sha256)  # fmt: skip
            except IntegridadeViolada:
                self._executar(partial(_bloquear, documento.id, contexto))
                continue
            entregues.append((documento, conteudo))
        return entregues

    def foto(self, contexto: Contexto, paciente_id: int) -> bytes | None:
        GUARDA.exigir(contexto, VER)
        fotos = self._executar(lambda uow: [d for d in vigentes_legiveis(uow.repositorio(RepositorioDocumentos),
                                                                        paciente_id) if d.tipo == FOTO])  # fmt: skip
        if not fotos:
            return None
        recente = max(fotos, key=lambda d: d.capturado_em)
        entregues = self._entregar(contexto, [recente])
        return entregues[0][1] if entregues else None

    def copia_ao_titular(self, contexto: Contexto, paciente_id: int) -> bytes:
        GUARDA.exigir(contexto, VER)
        documentos = self._executar(lambda uow: vigentes_legiveis(uow.repositorio(RepositorioDocumentos), paciente_id))
        documentos.sort(key=lambda d: (d.tipo, d.capturado_em))
        copia = pikepdf.new()
        abertos = []
        try:
            for documento, conteudo in self._entregar(contexto, documentos):
                if formato_da_origem(documento.origem) == "jpeg":
                    copia.pages.append(pagina_da_foto(copia, conteudo))
                    continue
                origem = pikepdf.open(io.BytesIO(conteudo))
                abertos.append(origem)
                copia.pages.extend(origem.pages)
            saida = io.BytesIO()
            copia.save(saida)
            return saida.getvalue()
        finally:
            for origem in abertos:
                origem.close()
