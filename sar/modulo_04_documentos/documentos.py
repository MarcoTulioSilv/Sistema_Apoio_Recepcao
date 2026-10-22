"""Consulta, download e revinculação de documentos (DDS §8.6). Toda leitura de conteúdo é auditada antes da entrega,
decifra em memória e confere o hash (DD-38); a divergência bloqueia o documento (P-19), numa transação à parte, para
o bloqueio ficar mesmo com a leitura recusada."""

from __future__ import annotations

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_04_documentos.armazenamento import Cofre
from sar.modulo_04_documentos.contrato import DocumentoDoTipo, PaginaDocumento, VersaoDocumento
from sar.modulo_04_documentos.ingestao import id_do_texto
from sar.modulo_04_documentos.paginas import JPEG, formato_da_origem, paginas_jpeg
from sar.modulo_08_dados.interfaces.documentos import DocumentoGravado, RepositorioDocumentos
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import IntegridadeViolada, NaoEncontrado, RegraViolada
from sar.nucleo.eventos import DocumentoRevinculado
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
LISTAR = "documento.listar"
VER = "documento.ver"
BAIXAR = "documento.baixar"
REVINCULAR = "documento.revincular"
TAMANHO_MOTIVO = 300


def formato_do(documento: DocumentoGravado) -> str:
    return formato_da_origem(documento.origem)


def cadeia(repo: RepositorioDocumentos, documento: DocumentoGravado) -> list[DocumentoGravado]:
    """Todas as versões ligadas a este documento, da primeira à vigente (DD-36)."""
    versoes = [documento]
    while versoes[0].substitui_id is not None and (anterior := repo.documento(versoes[0].substitui_id)) is not None:
        versoes.insert(0, anterior)
    while (seguinte_id := repo.sucessor(versoes[-1].id)) is not None and (
        seguinte := repo.documento(seguinte_id)
    ) is not None:
        versoes.append(seguinte)
    return versoes


class ServicoDocumentos:
    def __init__(self, executar: ExecutorDeOperacao, auditoria: AuditService, cofre: Cofre) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._cofre = cofre

    def listar(self, contexto: Contexto, paciente_id: int) -> list[DocumentoDoTipo]:
        GUARDA.exigir(contexto, LISTAR)

        def operacao(uow: UnidadeDeTrabalho) -> list[DocumentoDoTipo]:
            repo = uow.repositorio(RepositorioDocumentos)
            documentos = repo.do_paciente(paciente_id)
            nomes = {}
            for codigo in {d.tipo for d in documentos}:
                tipo = repo.tipo(codigo)
                nomes[codigo] = tipo.nome if tipo else codigo
            por_id = {d.id: d for d in documentos}
            substituidos = {d.substitui_id for d in documentos if d.substitui_id is not None}

            def versao(d: DocumentoGravado) -> VersaoDocumento:
                return VersaoDocumento(d.id.hex(), d.tipo, nomes[d.tipo], d.versao, d.paginas, d.origem,
                                       d.capturado_em, d.capturado_por, d.descartado_em, d.bloqueio_motivo)  # fmt: skip

            # Um tipo pode ter mais de uma vigente (documentos independentes, como dois termos de troca): as anteriores
            # de cada uma são as da sua cadeia.
            resultado = []
            for vigente in (d for d in documentos if d.id not in substituidos):
                anteriores = []
                anterior = por_id.get(vigente.substitui_id) if vigente.substitui_id else None
                while anterior is not None:
                    anteriores.append(versao(anterior))
                    anterior = por_id.get(anterior.substitui_id) if anterior.substitui_id else None
                resultado.append(DocumentoDoTipo(vigente.tipo, nomes[vigente.tipo], versao(vigente), tuple(anteriores)))
            self._auditoria.registrar(uow, contexto, LISTAR, "paciente", str(paciente_id),
                                      {"quantidade": (None, len(documentos))})  # fmt: skip
            return sorted(resultado, key=lambda d: (d.nome_tipo, -d.vigente.capturado_em.timestamp()))

        return self._executar(operacao)

    def _conteudo(self, contexto: Contexto, documento_id: str, operacao_auditada: str) -> tuple[bytes, str]:
        """Audita, decifra e confere. Na divergência, bloqueia noutra transação e repassa o erro."""
        id_ = id_do_texto(documento_id)

        def operacao(uow: UnidadeDeTrabalho) -> DocumentoGravado:
            documento = uow.repositorio(RepositorioDocumentos).documento(id_)
            if documento is None:
                raise NaoEncontrado()
            if documento.descartado_em is not None or documento.chave_cifrada is None:
                raise RegraViolada("documento.descartado")
            if documento.bloqueado_em is not None:
                raise RegraViolada("documento.bloqueado")
            self._auditoria.registrar(uow, contexto, operacao_auditada, "documento", id_.hex())
            return documento

        documento = self._executar(operacao)
        try:
            conteudo = self._cofre.ler(id_, documento.arquivo, documento.chave_cifrada or b"", documento.nonce,
                                       documento.hash_sha256)  # fmt: skip
        except IntegridadeViolada:
            self._executar(lambda uow: uow.repositorio(RepositorioDocumentos).bloquear(
                id_, contexto.instante, "hash_divergente"))  # fmt: skip
            raise
        return conteudo, formato_do(documento)

    def pagina(self, contexto: Contexto, documento_id: str, numero: int) -> PaginaDocumento:
        GUARDA.exigir(contexto, VER)
        conteudo, formato = self._conteudo(contexto, documento_id, VER)
        paginas = paginas_jpeg(conteudo, formato)
        if not 1 <= numero <= len(paginas):
            raise NaoEncontrado()
        return PaginaDocumento(paginas[numero - 1], JPEG)

    def baixar(self, contexto: Contexto, documento_id: str) -> tuple[bytes, str]:
        GUARDA.exigir(contexto, BAIXAR)
        conteudo, formato = self._conteudo(contexto, documento_id, BAIXAR)
        return conteudo, JPEG if formato == "jpeg" else "application/pdf"

    def revincular(self, contexto: Contexto, documento_id: str, paciente_id: int, motivo: str) -> None:
        GUARDA.exigir(contexto, REVINCULAR)
        motivo = motivo.strip()
        if not motivo or len(motivo) > TAMANHO_MOTIVO:
            raise RegraViolada("revinculo.motivo")
        id_ = id_do_texto(documento_id)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repo = uow.repositorio(RepositorioDocumentos)
            documento = repo.documento(id_)
            if documento is None:
                raise NaoEncontrado()
            if documento.paciente_id == paciente_id:
                raise RegraViolada("revinculo.mesmo_paciente")
            if not repo.paciente_ativo(paciente_id):
                raise RegraViolada("paciente.anulado")
            versoes = cadeia(repo, documento)
            repo.revincular([v.id for v in versoes], paciente_id)
            for versao in versoes:
                alteracao: dict[str, tuple[object, object]] = {"paciente_id": (versao.paciente_id, paciente_id)}
                self._auditoria.registrar(
                    uow, contexto, REVINCULAR, "documento", versao.id.hex(), alteracao, motivo=motivo
                )
                uow.publicar(DocumentoRevinculado(versao.id, versao.paciente_id, paciente_id))

        self._executar(operacao)
