"""Ciclo dos modelos .docx (DDS §9.2, DD-42, DD-103): a administração baixa, edita no Word, envia (validação e
prévia com paciente fictício), ativa e, se precisar, reverte. A versão 0 é o modelo inicial embutido no pacote."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_05_emissao import comum, ficticios
from sar.modulo_05_emissao.contrato import Envio, Modelo, ModeloResumo, VersaoModelo
from sar.modulo_05_emissao.conversor import ConversorDocumentos
from sar.modulo_05_emissao.preenchimento import preencher
from sar.modulo_05_emissao.validacao import validar
from sar.modulo_05_emissao.variaveis import FICTICIOS, nomes, variaveis
from sar.modulo_06_configuracao.contrato import Referencias
from sar.modulo_08_dados.interfaces.emissao import RepositorioModelo
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
PASTA_INICIAIS = Path(__file__).resolve().parent / "modelos_iniciais"


def embutido(modelo: Modelo) -> bytes:
    """A versão 0 (DD-103)."""
    return (PASTA_INICIAIS / f"{modelo.value}.docx").read_bytes()


def _hash(arquivo: bytes) -> str:
    return hashlib.sha256(arquivo).hexdigest()


def arquivo_ativo(uow: UnidadeDeTrabalho, modelo: Modelo) -> tuple[int, bytes]:
    """A versão ativa e o arquivo dela, para a emissão (DD-42: só modelo ativo e validado)."""
    repositorio = uow.repositorio(RepositorioModelo)
    ativo = repositorio.ativo(modelo.value)
    if ativo is None:
        return 0, embutido(modelo)
    arquivo = repositorio.arquivo(modelo.value, ativo.versao)
    if arquivo is None:
        raise NaoEncontrado()
    return ativo.versao, arquivo


class ServicoModelos:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        referencias: Referencias,
        conversor: ConversorDocumentos,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._referencias = referencias
        self._conversor = conversor

    def listar(self, contexto: Contexto) -> list[ModeloResumo]:
        GUARDA.exigir(contexto, "emissao.modelo.enviar")

        def operacao(uow: UnidadeDeTrabalho) -> list[ModeloResumo]:
            resumos = []
            for modelo in Modelo:
                enviadas = uow.repositorio(RepositorioModelo).versoes(modelo.value)
                versoes = [VersaoModelo(v.versao, v.hash_sha256, v.enviado_em, v.enviado_por, v.ativo, v.ativado_em)
                           for v in enviadas]  # fmt: skip
                nenhuma_ativa = not any(v.ativo for v in versoes)
                versoes.append(VersaoModelo(0, _hash(embutido(modelo)), None, None, nenhuma_ativa, None))
                resumos.append(ModeloResumo(modelo, tuple(versoes), variaveis(modelo)))
            return resumos

        return self._executar(operacao)

    def baixar(self, contexto: Contexto, modelo: Modelo, versao: int | None = None) -> bytes:
        GUARDA.exigir(contexto, "emissao.modelo.enviar")
        return self._executar(lambda uow: self._arquivo(uow, modelo, versao))

    def enviar(self, contexto: Contexto, modelo: Modelo, arquivo: bytes) -> Envio:
        GUARDA.exigir(contexto, "emissao.modelo.enviar")
        usuario_id = _usuario(contexto)
        validacao = validar(arquivo, modelo)
        if not validacao.aprovado:
            raise RegraViolada("modelo.invalido", {"problemas": [(p.codigo, p.detalhe) for p in validacao.problemas]})
        previa = self._previa(contexto, modelo, arquivo)  # fora da transação: o conversor é efeito externo (DD-59)
        hash_sha256 = _hash(arquivo)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioModelo)
            repositorio.travar(modelo.value)
            versao = max((v.versao for v in repositorio.versoes(modelo.value)), default=0) + 1
            repositorio.criar(modelo.value, versao, arquivo, hash_sha256, contexto.instante, usuario_id)
            self._auditoria.registrar(
                uow, contexto, "emissao.modelo.enviar", "modelo_documento", f"{modelo.value}:{versao}",
                {"hash_sha256": (None, hash_sha256)},
            )  # fmt: skip
            return versao

        return Envio(self._executar(operacao), validacao.avisos, previa)

    def previa(self, contexto: Contexto, modelo: Modelo, versao: int) -> bytes:
        GUARDA.exigir(contexto, "emissao.modelo.enviar")
        arquivo = self._executar(lambda uow: self._arquivo(uow, modelo, versao))
        return self._previa(contexto, modelo, arquivo)

    def ativar(self, contexto: Contexto, modelo: Modelo, versao: int) -> None:
        usuario_id = _usuario(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioModelo)
            repositorio.travar(modelo.value)
            enviadas = {v.versao: v for v in repositorio.versoes(modelo.value)}
            if versao != 0 and versao not in enviadas:
                raise NaoEncontrado()
            atual = next((v.versao for v in enviadas.values() if v.ativo), 0)
            GUARDA.exigir(contexto, "emissao.modelo.ativar" if versao > atual else "emissao.modelo.reverter")
            if versao == atual:
                return
            antes = enviadas[atual].hash_sha256 if atual else _hash(embutido(modelo))
            depois = enviadas[versao].hash_sha256 if versao else _hash(embutido(modelo))
            repositorio.ativar(modelo.value, versao or None, contexto.instante, usuario_id)
            operacao_auditada = "emissao.modelo.ativar" if versao > atual else "emissao.modelo.reverter"
            self._auditoria.registrar(
                uow, contexto, operacao_auditada, "modelo_documento", modelo.value,
                {"versao": (atual, versao), "hash_sha256": (antes, depois)},
            )  # fmt: skip

        self._executar(operacao)

    # ---------------------------------------------------------------- apoio
    @staticmethod
    def _arquivo(uow: UnidadeDeTrabalho, modelo: Modelo, versao: int | None) -> bytes:
        if versao is None:
            return arquivo_ativo(uow, modelo)[1]
        if versao == 0:
            return embutido(modelo)
        arquivo = uow.repositorio(RepositorioModelo).arquivo(modelo.value, versao)
        if arquivo is None:
            raise NaoEncontrado()
        return arquivo

    def _previa(self, contexto: Contexto, modelo: Modelo, arquivo: bytes) -> bytes:
        """Paciente fictício, com os dados institucionais vigentes (ou fictícios) e o logotipo da clínica."""
        comuns = self._executar(lambda uow: comum.ler(uow, self._referencias, self._auditoria, contexto.instante))
        permitidas = nomes(modelo)
        valores = {nome: valor for nome, valor in {**comuns.valores, **FICTICIOS}.items() if nome in permitidas}
        imagens = {"logotipo": comuns.logotipo or ficticios.logotipo(), "foto": ficticios.foto()}
        try:
            docx = preencher(arquivo, valores, {n: i for n, i in imagens.items() if n in permitidas})
        except Exception:  # o modelo passou na validação, mas o preenchimento falhou: não é aceito
            raise RegraViolada("modelo.invalido", {"problemas": [("preenchimento.falhou", None)]}) from None
        return self._conversor.para_pdf(docx)


def _usuario(contexto: Contexto) -> int:
    if contexto.usuario_id is None:
        raise AcessoNegado()
    return contexto.usuario_id
