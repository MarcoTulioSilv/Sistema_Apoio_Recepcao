"""Serviços do MOD-06 (DDS §10): parâmetros declarados no núcleo (DD-48, DD-73), convênios, municípios, dados
institucionais e logotipo (RF-1201, RF-1202) e faixas etárias (RF-1206)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_06_configuracao import logotipo as logo
from sar.modulo_06_configuracao.contrato import (
    Convenio,
    DadosInstitucionais,
    FaixaEtaria,
    Institucional,
    Municipio,
    ParametroVigente,
    Valor,
)
from sar.modulo_06_configuracao.regras import (
    LIMITE_BUSCA_MUNICIPIO,
    de_texto,
    para_texto,
    termo_de_busca,
    validar,
    validar_institucional,
    validar_nome_convenio,
    validar_uf,
)
from sar.modulo_08_dados.interfaces.parametros import RepositorioParametro, ValorGravado
from sar.modulo_08_dados.interfaces.referencias import (
    DadosConvenio,
    DadosInstituicao,
    DadosMunicipio,
    RepositorioConvenio,
    RepositorioInstituicao,
    RepositorioMunicipio,
)
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.logs import campos_do_erro
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


def _convenio(dados: DadosConvenio) -> Convenio:
    return Convenio(dados.id, dados.nome, dados.ativo)


def _municipio(dados: DadosMunicipio) -> Municipio:
    return Municipio(dados.codigo, dados.nome, dados.uf)


def _institucional(uow: UnidadeDeTrabalho) -> Institucional | None:
    dados = uow.repositorio(RepositorioInstituicao).obter()
    if dados is None:
        return None
    municipio = uow.repositorio(RepositorioMunicipio).por_codigo(dados.municipio)
    if municipio is None:  # a chave estrangeira garante; só por segurança de tipo
        raise NaoEncontrado()
    return Institucional(dados.nome, dados.endereco, dados.cep, _municipio(municipio), dados.telefone, dados.cnpj,
                         dados.tem_logotipo)  # fmt: skip


def _hash(conteudo: bytes | None) -> str | None:
    return hashlib.sha256(conteudo).hexdigest() if conteudo is not None else None


def _buscar_municipios(uow: UnidadeDeTrabalho, termo: str, uf: str | None) -> list[Municipio]:
    sigla = validar_uf(uf) if uf is not None else None
    limpo = termo_de_busca(termo)
    if limpo is None:
        return []
    achados = uow.repositorio(RepositorioMunicipio).buscar(limpo, sigla, LIMITE_BUSCA_MUNICIPIO)
    return [_municipio(m) for m in achados]


class ServicoReferencias:
    """Implementa o Referencias do contrato: leitura na unidade de trabalho de quem chama."""

    def convenios_ativos(self, uow: UnidadeDeTrabalho) -> list[Convenio]:
        return [_convenio(c) for c in uow.repositorio(RepositorioConvenio).listar() if c.ativo]

    def convenio(self, uow: UnidadeDeTrabalho, id: int) -> Convenio | None:
        dados = uow.repositorio(RepositorioConvenio).por_id(id)
        return _convenio(dados) if dados is not None else None

    def municipio(self, uow: UnidadeDeTrabalho, codigo: str) -> Municipio | None:
        dados = uow.repositorio(RepositorioMunicipio).por_codigo(codigo)
        return _municipio(dados) if dados is not None else None

    def buscar_municipios(self, uow: UnidadeDeTrabalho, termo: str, uf: str | None = None) -> list[Municipio]:
        return _buscar_municipios(uow, termo, uf)

    def institucional(self, uow: UnidadeDeTrabalho) -> Institucional | None:
        return _institucional(uow)

    def logotipo(self, uow: UnidadeDeTrabalho) -> bytes | None:
        return uow.repositorio(RepositorioInstituicao).logotipo()

    def faixas_etarias(self, uow: UnidadeDeTrabalho) -> list[FaixaEtaria]:
        faixas = uow.repositorio(RepositorioInstituicao).faixas_etarias()
        return [FaixaEtaria(f.inicio, f.fim, f.rotulo) for f in faixas]


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

    # ---------------------------------------------------------------- dados de referência (DDS §10.2)
    def listar_convenios(self, contexto: Contexto) -> list[Convenio]:
        GUARDA.exigir(contexto, "config.consultar")
        return self._executar(lambda uow: [_convenio(c) for c in uow.repositorio(RepositorioConvenio).listar()])

    def buscar_municipios(self, contexto: Contexto, termo: str, uf: str | None = None) -> list[Municipio]:
        GUARDA.exigir(contexto, "config.consultar")
        return self._executar(lambda uow: _buscar_municipios(uow, termo, uf))

    def listar_municipios(self, contexto: Contexto, uf: str) -> list[Municipio]:
        GUARDA.exigir(contexto, "config.consultar")
        sigla = validar_uf(uf)
        return self._executar(lambda uow: [_municipio(m) for m in uow.repositorio(RepositorioMunicipio).da_uf(sigla)])

    def incluir_convenio(self, contexto: Contexto, nome: str) -> int:
        GUARDA.exigir(contexto, "config.convenio.gerir")
        limpo = validar_nome_convenio(nome)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            convenios = uow.repositorio(RepositorioConvenio)
            if convenios.por_nome(limpo) is not None:
                raise RegraViolada("convenio.nome_repetido")
            convenio_id = convenios.criar(limpo)
            self._auditoria.registrar(
                uow, contexto, "config.convenio.gerir", "convenio", str(convenio_id),
                {"nome": (None, limpo), "ativo": (None, True)},
            )  # fmt: skip
            return convenio_id

        return self._com_nome_unico(lambda: self._executar(operacao))

    def renomear_convenio(self, contexto: Contexto, convenio_id: int, nome: str) -> None:
        GUARDA.exigir(contexto, "config.convenio.gerir")
        limpo = validar_nome_convenio(nome)

        def mudar(uow: UnidadeDeTrabalho, atual: DadosConvenio) -> DadosConvenio:
            outro = uow.repositorio(RepositorioConvenio).por_nome(limpo)
            if outro is not None and outro.id != atual.id:
                raise RegraViolada("convenio.nome_repetido")
            return DadosConvenio(atual.id, limpo, atual.ativo)

        self._com_nome_unico(lambda: self._alterar_convenio(contexto, convenio_id, mudar))

    def inativar_convenio(self, contexto: Contexto, convenio_id: int) -> None:
        GUARDA.exigir(contexto, "config.convenio.gerir")
        self._alterar_convenio(contexto, convenio_id, lambda _, c: DadosConvenio(c.id, c.nome, False))

    def reativar_convenio(self, contexto: Contexto, convenio_id: int) -> None:
        GUARDA.exigir(contexto, "config.convenio.gerir")
        self._alterar_convenio(contexto, convenio_id, lambda _, c: DadosConvenio(c.id, c.nome, True))

    # ---------------------------------------------------------------- dados institucionais (RF-1201, RF-1202)
    def ver_institucional(self, contexto: Contexto) -> Institucional | None:
        GUARDA.exigir(contexto, "config.consultar")
        return self._executar(_institucional)

    def alterar_institucional(self, contexto: Contexto, dados: DadosInstitucionais) -> None:
        GUARDA.exigir(contexto, "config.institucional.alterar")
        limpo = validar_institucional(dados)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            municipio = uow.repositorio(RepositorioMunicipio).por_codigo(limpo.municipio)
            if municipio is None:
                raise RegraViolada("instituicao.municipio")
            repositorio = uow.repositorio(RepositorioInstituicao)
            atual = repositorio.obter(travar=True)
            novo = DadosInstituicao(limpo.nome, limpo.endereco, limpo.cep, municipio.codigo, municipio.uf,
                                    limpo.telefone, limpo.cnpj, atual.tem_logotipo if atual else False)  # fmt: skip
            campos = ("nome", "endereco", "cep", "municipio", "uf", "telefone", "cnpj")
            alteracoes = {
                campo: (getattr(atual, campo) if atual else None, getattr(novo, campo))
                for campo in campos
                if atual is None or getattr(atual, campo) != getattr(novo, campo)
            }
            if not alteracoes:
                return  # nada muda, nada é gravado nem auditado (DD-10)
            repositorio.gravar(novo)
            self._auditoria.registrar(uow, contexto, "config.institucional.alterar", "instituicao", "1", alteracoes)

        self._executar(operacao)

    def enviar_logotipo(self, contexto: Contexto, arquivo: bytes) -> None:
        GUARDA.exigir(contexto, "config.logotipo.enviar")
        png = logo.processar(arquivo)  # no filho, antes da transação (DD-50)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioInstituicao)
            if repositorio.obter(travar=True) is None:
                raise RegraViolada("instituicao.ausente")
            antes = _hash(repositorio.logotipo())
            depois = _hash(png)
            if antes == depois:
                return
            repositorio.gravar_logotipo(png)
            self._auditoria.registrar(
                uow, contexto, "config.logotipo.enviar", "instituicao", "1", {"logotipo_sha256": (antes, depois)}
            )

        self._executar(operacao)

    def logotipo(self, contexto: Contexto) -> bytes | None:
        GUARDA.exigir(contexto, "config.consultar")
        return self._executar(lambda uow: uow.repositorio(RepositorioInstituicao).logotipo())

    def _alterar_convenio(
        self,
        contexto: Contexto,
        convenio_id: int,
        mudar: Callable[[UnidadeDeTrabalho, DadosConvenio], DadosConvenio],
    ) -> None:
        """Trava a linha, aplica a mudança e audita só o que mudou; sem mudança, nada é gravado (DD-10)."""

        def operacao(uow: UnidadeDeTrabalho) -> None:
            convenios = uow.repositorio(RepositorioConvenio)
            atual = convenios.por_id(convenio_id, travar=True)
            if atual is None:
                raise NaoEncontrado()
            novo = mudar(uow, atual)
            alteracoes: dict[str, tuple[object, object]] = {}
            if novo.nome != atual.nome:
                alteracoes["nome"] = (atual.nome, novo.nome)
            if novo.ativo != atual.ativo:
                alteracoes["ativo"] = (atual.ativo, novo.ativo)
            if not alteracoes:
                return
            convenios.alterar(convenio_id, novo.nome, novo.ativo)
            self._auditoria.registrar(uow, contexto, "config.convenio.gerir", "convenio", str(convenio_id), alteracoes)

        self._executar(operacao)

    @staticmethod
    def _com_nome_unico[R](chamada: Callable[[], R]) -> R:
        """Duas inclusões simultâneas do mesmo nome: a restrição do banco barra a segunda."""
        try:
            return chamada()
        except Exception as erro:
            if campos_do_erro(erro).get("restricao") == "uq_convenio__nome":
                raise RegraViolada("convenio.nome_repetido") from None
            raise
