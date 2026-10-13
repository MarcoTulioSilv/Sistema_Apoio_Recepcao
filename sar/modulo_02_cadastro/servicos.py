"""Serviços do MOD-02 Cadastro (DDS §6): paciente, busca, ficha e as leituras para os outros módulos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from datetime import date, timedelta

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import (
    CoberturaFicha,
    ContatoFicha,
    DadosPaciente,
    Ficha,
    Identificacao,
    PeriodoFicha,
    PeriodoRef,
    Sexo,
    TelefoneFicha,
    TipoCobertura,
    TipoEvento,
    TipoTelefone,
)
from sar.modulo_02_cadastro.regras import (
    campos_alterados,
    chave_triade,
    digitos,
    idade,
    normalizar,
    pendencias,
    situacao,
    verificar_inicio,
    verificar_minimo,
)
from sar.modulo_06_configuracao.contrato import Municipio, Referencias
from sar.modulo_08_dados.interfaces.pacientes import (
    CamposPaciente,
    ColunaUnica,
    PacienteGravado,
    PeriodoGravado,
    RepositorioPaciente,
)
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, ConfirmacaoNecessaria, ConflitoDeVersao, NaoEncontrado, RegraViolada
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
UF_RESIDENCIA = "GO"  # §6.2: residência só em Goiás
MINIMO_BUSCA = 2
LIMITE_BUSCA = 50
COLUNAS_UNICAS: tuple[ColunaUnica, ...] = ("prontuario", "cpf", "cns")
_RESTRICOES_UNICAS = {f"uq_paciente__{coluna}": coluna for coluna in COLUNAS_UNICAS}


def hoje_na_clinica(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO_CLINICA).date()


# ------------------------------------------------------------------ conversões
def _campos(dados: DadosPaciente) -> CamposPaciente:
    """Só depois de verificar_minimo: nome e prontuário presentes."""
    if dados.nome is None or dados.prontuario is None:
        raise RuntimeError("dados sem o mínimo da P-03")
    valores = {campo.name: getattr(dados, campo.name) for campo in fields(DadosPaciente)}
    valores["sexo"] = dados.sexo.value if dados.sexo is not None else None
    return CamposPaciente(**valores)


def _dados(campos: CamposPaciente) -> DadosPaciente:
    valores = {campo.name: getattr(campos, campo.name) for campo in fields(DadosPaciente)}
    valores["sexo"] = Sexo(campos.sexo) if campos.sexo is not None else None
    return DadosPaciente(**valores)


def _identificacao(p: PacienteGravado) -> Identificacao:
    c = p.campos
    return Identificacao(p.id, c.nome, c.prontuario, c.data_nascimento, c.nome_mae)


def _triade(c: CamposPaciente | DadosPaciente) -> tuple[str, date, str] | None:
    return chave_triade(c.nome, c.data_nascimento, c.nome_mae)


def _com_unicidade[R](chamada: Callable[[], R]) -> R:
    """Duas gravações simultâneas do mesmo número: a restrição do banco barra a segunda (INV-07, INV-15)."""
    try:
        return chamada()
    except Exception as erro:
        coluna = _RESTRICOES_UNICAS.get(campos_do_erro(erro).get("restricao") or "")
        if coluna is not None:
            raise RegraViolada(f"{coluna}.repetido") from None
        raise


# ------------------------------------------------------------------ verificações dentro da transação
class _Verificacoes:
    def __init__(self, referencias: Referencias) -> None:
        self._referencias = referencias

    def municipios(self, uow: UnidadeDeTrabalho, dados: DadosPaciente) -> None:
        if dados.municipio is not None:
            residencia = self._referencias.municipio(uow, dados.municipio)
            if residencia is None:
                raise RegraViolada("municipio.inexistente")
            if residencia.uf != UF_RESIDENCIA:
                raise RegraViolada("municipio.fora_de_goias")
        if dados.naturalidade_municipio is not None and (
            self._referencias.municipio(uow, dados.naturalidade_municipio) is None
        ):
            raise RegraViolada("naturalidade_municipio.inexistente")

    @staticmethod
    def unicos(repositorio: RepositorioPaciente, dados: DadosPaciente, proprio: int | None) -> None:
        """A recusa informa quem já usa o número (DEC-59)."""
        for coluna in COLUNAS_UNICAS:
            valor = getattr(dados, coluna)
            if valor is None:
                continue
            outro = repositorio.quem_usa(coluna, valor)
            if outro is not None and outro != proprio:
                raise RegraViolada(f"{coluna}.repetido", {"paciente_id": outro})

    @staticmethod
    def candidatos_triade(
        repositorio: RepositorioPaciente, dados: CamposPaciente | DadosPaciente, proprio: int | None
    ) -> list[PacienteGravado]:
        """Tríade coincidente (INV-08), sem o próprio e sem os pares já descartados."""
        chave = _triade(dados)
        if chave is None:
            return []
        return [
            p
            for p in repositorio.por_nascimento(chave[1])
            if p.id != proprio
            and _triade(p.campos) == chave
            and not (proprio is not None and repositorio.duplicidade_descartada(proprio, p.id))
        ]


class ServicoPacientes:
    def __init__(self, executar: ExecutorDeOperacao, auditoria: AuditService, referencias: Referencias) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._referencias = referencias
        self._verificar = _Verificacoes(referencias)

    # ---------------------------------------------------------------- escrita
    def criar(
        self, contexto: Contexto, dados: DadosPaciente, inicio: date | None, confirmar_duplicidade: bool = False
    ) -> int:
        GUARDA.exigir(contexto, "cadastro.paciente.criar")
        dados = normalizar(dados, hoje_na_clinica(contexto))
        verificar_minimo(dados, inicio)
        if inicio is None:
            raise RuntimeError("inalcançável: verificar_minimo exige a data de início")
        verificar_inicio(inicio, dados.data_nascimento)
        campos = _campos(dados)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioPaciente)
            self._verificar.municipios(uow, dados)
            self._verificar.unicos(repositorio, dados, None)
            candidatos = self._verificar.candidatos_triade(repositorio, dados, None)
            if candidatos and not confirmar_duplicidade:
                raise ConfirmacaoNecessaria("triade", {"candidatos": [p.id for p in candidatos]})
            paciente_id = repositorio.criar(campos, cep_verificado=False, em=contexto.instante)
            repositorio.abrir_periodo(paciente_id, inicio)
            alteracoes = campos_alterados(DadosPaciente(), dados)
            alteracoes["periodo_inicio"] = (None, inicio)
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.criar", "paciente", str(paciente_id), alteracoes
            )
            return paciente_id

        return _com_unicidade(lambda: self._executar(operacao))

    def atualizar(self, contexto: Contexto, paciente_id: int, versao: int, dados: DadosPaciente) -> int:
        GUARDA.exigir(contexto, "cadastro.paciente.atualizar")
        hoje = hoje_na_clinica(contexto)
        dados = normalizar(dados, hoje)
        verificar_minimo(dados, hoje)  # a data de início já existe: aqui só nome e prontuário contam
        campos = _campos(dados)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioPaciente)
            atual = repositorio.por_id(paciente_id, travar=True)
            if atual is None or atual.anulado_em is not None:
                raise NaoEncontrado()
            if atual.versao != versao:
                raise ConflitoDeVersao(None, None)
            periodos = repositorio.periodos(paciente_id)
            if periodos:
                verificar_inicio(periodos[0].inicio, dados.data_nascimento)
            alteracoes = campos_alterados(_dados(atual.campos), dados)
            if not alteracoes:
                return versao  # nada mudou: nada é gravado nem auditado (DD-10)
            self._verificar.municipios(uow, dados)
            self._verificar.unicos(repositorio, dados, paciente_id)
            cep_verificado = atual.cep_verificado and campos.cep == atual.campos.cep
            if not repositorio.atualizar(paciente_id, versao, campos, cep_verificado):
                raise ConflitoDeVersao(None, None)
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.atualizar", "paciente", str(paciente_id), alteracoes
            )
            return versao + 1

        return _com_unicidade(lambda: self._executar(operacao))

    def descartar_duplicidade(self, contexto: Contexto, paciente_id: int, outro_id: int) -> None:
        GUARDA.exigir(contexto, "cadastro.paciente.descartar_duplicidade")
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise AcessoNegado()

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            par = [repositorio.por_id(i) for i in (paciente_id, outro_id)]
            if any(p is None or p.anulado_em is not None for p in par) or paciente_id == outro_id:
                raise NaoEncontrado()
            a, b = (p for p in par if p is not None)
            if _triade(a.campos) is None or _triade(a.campos) != _triade(b.campos):
                raise RegraViolada("duplicidade.sem_coincidencia")
            if repositorio.duplicidade_descartada(a.id, b.id):
                return
            repositorio.descartar_duplicidade(a.id, b.id, usuario_id, contexto.instante)
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.descartar_duplicidade", "paciente", str(min(a.id, b.id)),
                {"duplicidade_descartada_com": (None, max(a.id, b.id))},
            )  # fmt: skip

        self._executar(operacao)

    # ---------------------------------------------------------------- leitura
    def buscar(self, contexto: Contexto, termo: str) -> list[Identificacao]:
        GUARDA.exigir(contexto, "cadastro.paciente.buscar")
        limpo = " ".join(termo.split())
        if len(limpo) < MINIMO_BUSCA:
            return []
        try:
            numero = digitos(limpo, "busca")
        except RegraViolada:
            numero = None
        exato = numero if numero is not None and len(numero) in (11, 15) else limpo

        def operacao(uow: UnidadeDeTrabalho) -> list[Identificacao]:
            achados = uow.repositorio(RepositorioPaciente).buscar(limpo, exato, LIMITE_BUSCA)
            return [_identificacao(p) for p in achados]

        return self._executar(operacao)

    def ver_ficha(self, contexto: Contexto, paciente_id: int) -> Ficha:
        GUARDA.exigir(contexto, "cadastro.paciente.ver_ficha")
        hoje = hoje_na_clinica(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> Ficha:
            repositorio = uow.repositorio(RepositorioPaciente)
            paciente = repositorio.por_id(paciente_id)
            if paciente is None or paciente.anulado_em is not None:
                raise NaoEncontrado()
            dados = _dados(paciente.campos)
            periodos = repositorio.periodos(paciente_id)
            telefones = repositorio.telefones(paciente_id)

            def telefone_ficha(contato_id: int | None) -> tuple[TelefoneFicha, ...]:
                return tuple(
                    TelefoneFicha(t.id, t.ddd, t.numero, TipoTelefone(t.tipo))
                    for t in telefones
                    if t.contato_id == contato_id and (contato_id is not None or t.paciente_id == paciente_id)
                )

            return Ficha(
                paciente_id=paciente.id,
                versao=paciente.versao,
                dados=dados,
                cep_verificado=paciente.cep_verificado,
                idade=idade(dados.data_nascimento, hoje) if dados.data_nascimento else None,
                situacao=situacao([_evento(p) for p in periodos], alocado=False),  # alocação: MOD-03
                pendencias=pendencias(dados, paciente.cep_verificado),
                residencia=self._municipio(uow, dados.municipio),
                naturalidade=self._municipio(uow, dados.naturalidade_municipio),
                periodos=self._periodos_ficha(uow, repositorio, periodos),
                telefones=telefone_ficha(None),
                contatos=tuple(
                    ContatoFicha(c.id, c.nome, c.parentesco, telefone_ficha(c.id))
                    for c in repositorio.contatos(paciente_id)
                ),
                possiveis_duplicatas=tuple(
                    _identificacao(p) for p in self._verificar.candidatos_triade(repositorio, dados, paciente_id)
                ),
            )

        return self._executar(operacao)

    def _municipio(self, uow: UnidadeDeTrabalho, codigo: str | None) -> Municipio | None:
        return self._referencias.municipio(uow, codigo) if codigo is not None else None

    def _periodos_ficha(
        self, uow: UnidadeDeTrabalho, repositorio: RepositorioPaciente, periodos: list[PeriodoGravado]
    ) -> tuple[PeriodoFicha, ...]:
        coberturas = repositorio.coberturas([p.id for p in periodos])
        fichas = []
        for p in periodos:
            do_periodo = [c for c in coberturas if c.periodo_id == p.id]
            itens = []
            for i, c in enumerate(do_periodo):
                seguinte = do_periodo[i + 1].inicio if i + 1 < len(do_periodo) else None
                convenio = self._referencias.convenio(uow, c.convenio_id) if c.convenio_id is not None else None
                itens.append(
                    CoberturaFicha(
                        inicio=c.inicio,
                        ate=seguinte - timedelta(days=1) if seguinte is not None else None,
                        tipo=TipoCobertura(c.tipo),
                        convenio_nome=convenio.nome if convenio else None,
                        convenio_ativo=convenio.ativo if convenio else None,
                        carteirinha=c.carteirinha,
                    )
                )
            fichas.append(
                PeriodoFicha(
                    p.id,
                    p.inicio,
                    _evento(p),
                    p.evento_data,
                    p.evento_local,
                    p.evento_documento_id is not None,
                    tuple(itens),
                )
            )
        return tuple(fichas)


def _evento(p: PeriodoGravado) -> TipoEvento | None:
    return TipoEvento(p.evento_tipo) if p.evento_tipo is not None else None


class ServicoLeituraCadastro:
    """Implementa o LeituraCadastro do contrato."""

    @staticmethod
    def _vivo(uow: UnidadeDeTrabalho, paciente_id: int) -> PacienteGravado | None:
        paciente = uow.repositorio(RepositorioPaciente).por_id(paciente_id)
        return paciente if paciente is not None and paciente.anulado_em is None else None

    def identificacao(self, uow: UnidadeDeTrabalho, paciente_id: int) -> Identificacao | None:
        paciente = self._vivo(uow, paciente_id)
        return _identificacao(paciente) if paciente is not None else None

    def periodo_aberto_em(self, uow: UnidadeDeTrabalho, paciente_id: int, data: date) -> PeriodoRef | None:
        if self._vivo(uow, paciente_id) is None:
            return None
        for p in reversed(uow.repositorio(RepositorioPaciente).periodos(paciente_id)):
            if p.inicio <= data and (p.evento_data is None or data <= p.evento_data):
                return PeriodoRef(p.id, p.inicio, p.evento_data)
        return None

    def data_obito(self, uow: UnidadeDeTrabalho, paciente_id: int) -> date | None:
        if self._vivo(uow, paciente_id) is None:
            return None
        periodos = uow.repositorio(RepositorioPaciente).periodos(paciente_id)
        return next((p.evento_data for p in periodos if p.evento_tipo == TipoEvento.OBITO.value), None)

    def pacientes_com_periodo_aberto_em(self, uow: UnidadeDeTrabalho, data: date) -> list[int]:
        return uow.repositorio(RepositorioPaciente).pacientes_com_periodo_em(data)
