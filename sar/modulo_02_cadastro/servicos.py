"""Serviços do MOD-02 Cadastro (DDS §6): paciente, busca, ficha e as leituras para os outros módulos."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import date, timedelta
from typing import Literal

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import (
    CoberturaFicha,
    ContatoFicha,
    DadosCobertura,
    DadosContato,
    DadosPaciente,
    DadosTelefone,
    EnderecoSugerido,
    Ficha,
    Identificacao,
    PaginaPacientes,
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
    sem_acento,
    situacao,
    validar_cobertura,
    validar_contato,
    validar_telefone,
    verificar_abertura,
    verificar_inicio,
    verificar_inicio_cobertura,
    verificar_minimo,
)
from sar.modulo_06_configuracao.contrato import Municipio, Referencias
from sar.modulo_08_dados.interfaces.pacientes import (
    CamposPaciente,
    ColunaUnica,
    ContatoGravado,
    PacienteGravado,
    PeriodoGravado,
    RepositorioPaciente,
    TelefoneGravado,
)
from sar.modulo_08_dados.interfaces.rascunhos import RepositorioRascunho
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import (
    AcessoNegado,
    ConfirmacaoNecessaria,
    ConflitoDeVersao,
    IndisponivelExterno,
    NaoEncontrado,
    RegraViolada,
)
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.portas import EnderecoCep, ProvedorCep
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
UF_RESIDENCIA = "GO"  # §6.2: residência só em Goiás
MINIMO_BUSCA = 2
MINIMO_DIGITOS = 3  # CPF e CNS pelo começo só a partir daqui: com 1 ou 2 dígitos, viria quase todo o cadastro
LIMITE_BUSCA = 50
COLUNAS_UNICAS: tuple[ColunaUnica, ...] = ("prontuario", "cpf", "cns")
_RESTRICOES = {f"uq_paciente__{coluna}": f"{coluna}.repetido" for coluna in COLUNAS_UNICAS} | {
    "uq_periodo_tratamento__um_aberto": "INV-02",
    "uq_periodo_tratamento__inicio": "periodo.inicio_repetido",
    "uq_cobertura__inicio": "INV-09",
}


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


def dados_de(campos: CamposPaciente) -> DadosPaciente:
    """Os campos gravados como o DadosPaciente do contrato (também para as fontes de pendência)."""
    valores = {campo.name: getattr(campos, campo.name) for campo in fields(DadosPaciente)}
    valores["sexo"] = Sexo(campos.sexo) if campos.sexo is not None else None
    return DadosPaciente(**valores)


def _identificacao(p: PacienteGravado) -> Identificacao:
    """Só de paciente vivo: o anulado não tem mais nome nem prontuário (DD-89), e quem chama já o filtrou."""
    c = p.campos
    if c.nome is None or c.prontuario is None:
        raise RuntimeError("paciente anulado não tem identificação")
    return Identificacao(p.id, c.nome, c.prontuario, c.data_nascimento, c.nome_mae)


def _triade(c: CamposPaciente | DadosPaciente) -> tuple[str, date, str] | None:
    return chave_triade(c.nome, c.data_nascimento, c.nome_mae)


@dataclass(frozen=True, slots=True)
class _TelefoneLimpo:
    ddd: str
    numero: str
    tipo: str


def _telefones_limpos(telefones: Sequence[DadosTelefone], posicao: dict[str, int]) -> list[_TelefoneLimpo]:
    """Regras do telefone antes da transação, com a posição no erro; número repetido no mesmo dono é recusado."""
    limpos: list[_TelefoneLimpo] = []
    for i, telefone in enumerate(telefones):
        try:
            ddd, numero = validar_telefone(telefone.ddd, telefone.numero, telefone.tipo)
        except RegraViolada as erro:
            raise RegraViolada(erro.codigo, {**posicao, "telefone": i}) from None
        if any((t.ddd, t.numero) == (ddd, numero) for t in limpos):
            raise RegraViolada("telefone.repetido", {**posicao, "telefone": i})
        limpos.append(_TelefoneLimpo(ddd, numero, telefone.tipo.value))
    return limpos


def _contatos_limpos(contatos: Sequence[DadosContato]) -> list[tuple[str, str | None, list[_TelefoneLimpo]]]:
    limpos = []
    for j, contato in enumerate(contatos):
        try:
            nome, parentesco = validar_contato(contato.nome, contato.parentesco)
        except RegraViolada as erro:
            raise RegraViolada(erro.codigo, {"contato": j}) from None
        limpos.append((nome, parentesco, _telefones_limpos(contato.telefones, {"contato": j})))
    return limpos


def _com_unicidade[R](chamada: Callable[[], R]) -> R:
    """Duas gravações simultâneas que a verificação prévia não viu: a restrição do banco barra a segunda
    (INV-02, INV-07, INV-09, INV-15)."""
    try:
        return chamada()
    except Exception as erro:
        codigo = _RESTRICOES.get(campos_do_erro(erro).get("restricao") or "")
        if codigo is not None:
            raise RegraViolada(codigo) from None
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


def _cep_existe(provedor: ProvedorCep, cep: str | None) -> bool:
    """Para gravar o cadastro: fonte fora do ar ou CEP desconhecido deixam o CEP não verificado, com pendência,
    sem impedir a gravação (QAS-03). A consulta acontece antes da transação: rede nunca segura trava do banco."""
    if cep is None:
        return False
    try:
        return provedor.consultar(cep) is not None
    except IndisponivelExterno:
        return False


class ServicoPacientes:
    def __init__(
        self, executar: ExecutorDeOperacao, auditoria: AuditService, referencias: Referencias, cep: ProvedorCep
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._referencias = referencias
        self._verificar = _Verificacoes(referencias)
        self._cep = cep

    # ---------------------------------------------------------------- escrita
    def criar(
        self,
        contexto: Contexto,
        dados: DadosPaciente,
        inicio: date | None,
        confirmar_duplicidade: bool = False,
        cobertura: DadosCobertura | None = None,
        telefones: Sequence[DadosTelefone] = (),
        contatos: Sequence[DadosContato] = (),
    ) -> int:
        GUARDA.exigir(contexto, "cadastro.paciente.criar")
        dados = normalizar(dados, hoje_na_clinica(contexto))
        verificar_minimo(dados, inicio)
        if inicio is None:
            raise RuntimeError("inalcançável: verificar_minimo exige a data de início")
        verificar_inicio(inicio, dados.data_nascimento)
        campos = _campos(dados)
        carteirinha = (
            validar_cobertura(cobertura.tipo, cobertura.convenio_id, cobertura.carteirinha) if cobertura else None
        )
        telefones_limpos = _telefones_limpos(telefones, {})
        contatos_limpos = _contatos_limpos(contatos)
        cep_verificado = _cep_existe(self._cep, dados.cep)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioPaciente)
            self._verificar.municipios(uow, dados)
            self._verificar.unicos(repositorio, dados, None)
            candidatos = self._verificar.candidatos_triade(repositorio, dados, None)
            if candidatos and not confirmar_duplicidade:
                raise ConfirmacaoNecessaria("triade", {"candidatos": [p.id for p in candidatos]})
            paciente_id = repositorio.criar(campos, cep_verificado=cep_verificado, em=contexto.instante)
            periodo_id = repositorio.abrir_periodo(paciente_id, inicio)
            alteracoes = campos_alterados(DadosPaciente(), dados)
            alteracoes["periodo_inicio"] = (None, inicio)
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.criar", "paciente", str(paciente_id), alteracoes
            )
            if cobertura is not None:
                self._gravar_cobertura(uow, contexto, periodo_id, cobertura, carteirinha, inicio)
            self._gravar_telefones_e_contatos(uow, contexto, paciente_id, telefones_limpos, contatos_limpos)
            self._eliminar_rascunho(uow, contexto)
            return paciente_id

        return _com_unicidade(lambda: self._executar(operacao))

    def atualizar(self, contexto: Contexto, paciente_id: int, versao: int, dados: DadosPaciente) -> int:
        GUARDA.exigir(contexto, "cadastro.paciente.atualizar")
        hoje = hoje_na_clinica(contexto)
        dados = normalizar(dados, hoje)
        verificar_minimo(dados, hoje)  # a data de início já existe: aqui só nome e prontuário contam
        campos = _campos(dados)
        anterior = self._executar(lambda uow: uow.repositorio(RepositorioPaciente).por_id(paciente_id))
        cep_mudou = anterior is None or anterior.campos.cep != campos.cep
        cep_novo_verificado = _cep_existe(self._cep, campos.cep) if cep_mudou else False

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
            alteracoes = campos_alterados(dados_de(atual.campos), dados)
            if not alteracoes:
                return versao  # nada mudou: nada é gravado nem auditado (DD-10)
            self._verificar.municipios(uow, dados)
            self._verificar.unicos(repositorio, dados, paciente_id)
            cep_verificado = atual.cep_verificado if campos.cep == atual.campos.cep else cep_novo_verificado
            if not repositorio.atualizar(paciente_id, versao, campos, cep_verificado):
                raise ConflitoDeVersao(None, None)
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.atualizar", "paciente", str(paciente_id), alteracoes
            )
            return versao + 1

        return _com_unicidade(lambda: self._executar(operacao))

    def _gravar_telefones_e_contatos(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        paciente_id: int,
        telefones: list[_TelefoneLimpo],
        contatos: list[tuple[str, str | None, list[_TelefoneLimpo]]],
    ) -> None:
        """Mesma trilha do ContatoService: um registro por contato e por telefone (INV-12: um dono só)."""
        repositorio = uow.repositorio(RepositorioPaciente)

        def telefone(dono_paciente: int | None, contato_id: int | None, t: _TelefoneLimpo) -> None:
            telefone_id = repositorio.criar_telefone(dono_paciente, contato_id, t.ddd, t.numero, t.tipo)
            self._auditoria.registrar(
                uow, contexto, "cadastro.telefone.gerir", "telefone", str(telefone_id),
                {"paciente_id": (None, dono_paciente), "contato_id": (None, contato_id), "ddd": (None, t.ddd),
                 "numero": (None, t.numero), "tipo": (None, t.tipo)},
            )  # fmt: skip

        for t in telefones:
            telefone(paciente_id, None, t)
        for nome, parentesco, telefones_do_contato in contatos:
            contato_id = repositorio.criar_contato(paciente_id, nome, parentesco)
            self._auditoria.registrar(
                uow, contexto, "cadastro.contato.gerir", "contato", str(contato_id),
                {"paciente_id": (None, paciente_id), "nome": (None, nome), "parentesco": (None, parentesco)},
            )  # fmt: skip
            for t in telefones_do_contato:
                telefone(None, contato_id, t)

    def _eliminar_rascunho(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> None:
        """§6.6: o rascunho de quem salvou o cadastro é eliminado na mesma transação."""
        if contexto.usuario_id is None:
            return
        rascunhos = uow.repositorio(RepositorioRascunho)
        atual = rascunhos.do_usuario(contexto.usuario_id)
        if atual is not None and rascunhos.remover_do_usuario(contexto.usuario_id):
            self._auditoria.registrar(
                uow, contexto, "cadastro.rascunho.descartar", "rascunho_cadastro", str(atual.id), None, "virou cadastro"
            )

    def abrir_periodo(
        self, contexto: Contexto, paciente_id: int, inicio: date, cobertura: DadosCobertura | None = None
    ) -> int:
        GUARDA.exigir(contexto, "cadastro.periodo.abrir")
        carteirinha = (
            validar_cobertura(cobertura.tipo, cobertura.convenio_id, cobertura.carteirinha) if cobertura else None
        )

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioPaciente)
            paciente = _paciente_vivo(repositorio, paciente_id)
            periodos = repositorio.periodos(paciente_id)
            obito = next((p.evento_data for p in periodos if p.evento_tipo == TipoEvento.OBITO.value), None)
            aberto = any(p.evento_tipo is None for p in periodos)
            fim_anterior = periodos[-1].evento_data if periodos else None
            verificar_abertura(inicio, aberto, fim_anterior, obito)
            verificar_inicio(inicio, paciente.campos.data_nascimento)
            if any(p.inicio == inicio for p in periodos):
                raise RegraViolada("periodo.inicio_repetido")
            periodo_id = repositorio.abrir_periodo(paciente_id, inicio)
            self._auditoria.registrar(
                uow, contexto, "cadastro.periodo.abrir", "periodo_tratamento", str(periodo_id),
                {"paciente_id": (None, paciente_id), "inicio": (None, inicio)},
            )  # fmt: skip
            if cobertura is not None:
                self._gravar_cobertura(uow, contexto, periodo_id, cobertura, carteirinha, inicio)
            return periodo_id

        return _com_unicidade(lambda: self._executar(operacao))

    def registrar_cobertura(self, contexto: Contexto, periodo_id: int, cobertura: DadosCobertura, inicio: date) -> None:
        GUARDA.exigir(contexto, "cadastro.cobertura.registrar")
        carteirinha = validar_cobertura(cobertura.tipo, cobertura.convenio_id, cobertura.carteirinha)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            periodo = repositorio.periodo(periodo_id)
            if periodo is None:
                raise NaoEncontrado()
            _paciente_vivo(repositorio, periodo.paciente_id)  # trava o agregado: duas vigências não se cruzam
            self._gravar_cobertura(uow, contexto, periodo_id, cobertura, carteirinha, inicio)

        _com_unicidade(lambda: self._executar(operacao))

    def _gravar_cobertura(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        periodo_id: int,
        cobertura: DadosCobertura,
        carteirinha: str | None,
        inicio: date,
    ) -> None:
        """Com o agregado já travado: período, convênio ativo, início dentro do período e sem repetir (INV-09)."""
        repositorio = uow.repositorio(RepositorioPaciente)
        periodo = repositorio.periodo(periodo_id)
        if periodo is None:
            raise NaoEncontrado()
        if cobertura.convenio_id is not None:
            convenio = self._referencias.convenio(uow, cobertura.convenio_id)
            if convenio is None:
                raise NaoEncontrado()
            if not convenio.ativo:
                raise RegraViolada("cobertura.convenio_inativo")  # DD-49: inativo não entra em registro novo
        inicios = [c.inicio for c in repositorio.coberturas([periodo_id])]
        verificar_inicio_cobertura(inicio, periodo.inicio, periodo.evento_data, inicios)
        cobertura_id = repositorio.criar_cobertura(
            periodo_id, inicio, cobertura.tipo.value, cobertura.convenio_id, carteirinha
        )
        self._auditoria.registrar(
            uow, contexto, "cadastro.cobertura.registrar", "cobertura", str(cobertura_id),
            {"periodo_id": (None, periodo_id), "inicio": (None, inicio), "tipo": (None, cobertura.tipo.value),
             "convenio_id": (None, cobertura.convenio_id), "carteirinha": (None, carteirinha)},
        )  # fmt: skip

    def conferir_documento(
        self, contexto: Contexto, campo: Literal["cpf", "cns"], valor: str, paciente_id: int | None = None
    ) -> int | None:
        if not (
            GUARDA.pode(contexto, "cadastro.paciente.criar") or GUARDA.pode(contexto, "cadastro.paciente.atualizar")
        ):
            raise AcessoNegado()
        dados = DadosPaciente(cpf=valor) if campo == "cpf" else DadosPaciente(cns=valor)
        limpo: str | None = getattr(normalizar(dados, hoje_na_clinica(contexto)), campo)
        if limpo is None:
            return None
        outro = self._executar(lambda uow: uow.repositorio(RepositorioPaciente).quem_usa(campo, limpo))
        return outro if outro != paciente_id else None

    def verificar_cep(self, contexto: Contexto, paciente_id: int) -> bool:
        GUARDA.exigir(contexto, "cadastro.paciente.atualizar")
        paciente = self._executar(lambda uow: uow.repositorio(RepositorioPaciente).por_id(paciente_id))
        if paciente is None or paciente.anulado_em is not None:
            raise NaoEncontrado()
        cep = paciente.campos.cep
        if cep is None:
            raise RegraViolada("cep.ausente")
        existe = self._cep.consultar(cep) is not None  # IndisponivelExterno sobe: a pessoa tenta mais tarde

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            atual = _paciente_vivo(repositorio, paciente_id)
            if atual.campos.cep != cep or atual.cep_verificado == existe:
                return  # o CEP mudou no meio do caminho, ou nada muda
            repositorio.definir_cep_verificado(paciente_id, existe)
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.atualizar", "paciente", str(paciente_id),
                {"cep_verificado": (atual.cep_verificado, existe)},
            )  # fmt: skip

        self._executar(operacao)
        return existe

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
        nome, prontuario, numero = self._termos(limpo)

        def operacao(uow: UnidadeDeTrabalho) -> list[Identificacao]:
            achados = uow.repositorio(RepositorioPaciente).buscar(nome, prontuario, numero, LIMITE_BUSCA)
            # DDS §4.2: auditada só a quantidade; o termo pode ser nome ou CPF e não vai à trilha (DD-10).
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.buscar", "paciente", None, {"quantidade": (None, len(achados))}
            )
            return [_identificacao(p) for p in achados]

        return self._executar(operacao)

    def listar(self, contexto: Contexto, termo: str = "", deslocamento: int = 0, limite: int = 30) -> PaginaPacientes:
        GUARDA.exigir(contexto, "cadastro.paciente.buscar")
        limpo = " ".join(termo.split())
        nome, prontuario, numero = (None, None, None) if len(limpo) < MINIMO_BUSCA else self._termos(limpo)
        limite = max(1, min(limite, LIMITE_BUSCA))
        deslocamento = max(0, deslocamento)

        def operacao(uow: UnidadeDeTrabalho) -> PaginaPacientes:
            achados = uow.repositorio(RepositorioPaciente).buscar(nome, prontuario, numero, limite + 1, deslocamento)
            pagina = achados[:limite]
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.buscar", "paciente", None, {"quantidade": (None, len(pagina))}
            )
            return PaginaPacientes(tuple(_identificacao(p) for p in pagina), len(achados) > limite)

        return self._executar(operacao)

    @staticmethod
    def _termos(limpo: str) -> tuple[str, str, str | None]:
        """O termo como nome e como começo do prontuário; e, se for só número (a pontuação do CPF e do CNS é
        aceita), como começo do CPF ou do CNS, a partir de 3 dígitos, para a busca andar enquanto se digita."""
        try:
            numero = digitos(limpo, "busca")
        except RegraViolada:
            numero = None
        return limpo, limpo, numero if numero is not None and len(numero) >= MINIMO_DIGITOS else None

    def ver_ficha(self, contexto: Contexto, paciente_id: int) -> Ficha:
        GUARDA.exigir(contexto, "cadastro.paciente.ver_ficha")
        hoje = hoje_na_clinica(contexto)

        def operacao(uow: UnidadeDeTrabalho) -> Ficha:
            repositorio = uow.repositorio(RepositorioPaciente)
            paciente = repositorio.por_id(paciente_id)
            if paciente is None or paciente.anulado_em is not None:
                raise NaoEncontrado()
            self._auditoria.registrar(
                uow, contexto, "cadastro.paciente.ver_ficha", "paciente", str(paciente_id)
            )  # DEC-55
            dados = dados_de(paciente.campos)
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


def _paciente_vivo(repositorio: RepositorioPaciente, paciente_id: int) -> PacienteGravado:
    """Trava o agregado; NaoEncontrado se não existir ou estiver anulado."""
    paciente = repositorio.por_id(paciente_id, travar=True)
    if paciente is None or paciente.anulado_em is not None:
        raise NaoEncontrado()
    return paciente


def _mudancas(*trios: tuple[str, object, object]) -> dict[str, tuple[object, object]]:
    return {campo: (velho, novo) for campo, velho, novo in trios if velho != novo}


def _telefone_auditado(t: TelefoneGravado | None, novo: TelefoneGravado | None) -> dict[str, tuple[object, object]]:
    """Antes e depois de um telefone inteiro: inclusão (t None) ou remoção (novo None)."""
    campos = ("paciente_id", "contato_id", "ddd", "numero", "tipo")
    return _mudancas(*((c, getattr(t, c) if t else None, getattr(novo, c) if novo else None) for c in campos))


class ServicoContatos:
    """Implementa o ContatoService do contrato."""

    CONTATO = "cadastro.contato.gerir"
    TELEFONE = "cadastro.telefone.gerir"

    def __init__(self, executar: ExecutorDeOperacao, auditoria: AuditService) -> None:
        self._executar = executar
        self._auditoria = auditoria

    # ---------------------------------------------------------------- contatos
    def incluir_contato(self, contexto: Contexto, paciente_id: int, nome: str, parentesco: str | None) -> int:
        GUARDA.exigir(contexto, self.CONTATO)
        nome_limpo, parentesco_limpo = validar_contato(nome, parentesco)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioPaciente)
            _paciente_vivo(repositorio, paciente_id)
            contato_id = repositorio.criar_contato(paciente_id, nome_limpo, parentesco_limpo)
            alteracoes = _mudancas(
                ("paciente_id", None, paciente_id), ("nome", None, nome_limpo), ("parentesco", None, parentesco_limpo)
            )
            self._auditoria.registrar(uow, contexto, self.CONTATO, "contato", str(contato_id), alteracoes)
            return contato_id

        return self._executar(operacao)

    def alterar_contato(self, contexto: Contexto, contato_id: int, nome: str, parentesco: str | None) -> None:
        GUARDA.exigir(contexto, self.CONTATO)
        nome_limpo, parentesco_limpo = validar_contato(nome, parentesco)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            contato = _contato_vivo(repositorio, contato_id)
            alteracoes = _mudancas(
                ("nome", contato.nome, nome_limpo), ("parentesco", contato.parentesco, parentesco_limpo)
            )
            if not alteracoes:
                return  # DD-10
            repositorio.alterar_contato(contato_id, nome_limpo, parentesco_limpo)
            self._auditoria.registrar(uow, contexto, self.CONTATO, "contato", str(contato_id), alteracoes)

        self._executar(operacao)

    def remover_contato(self, contexto: Contexto, contato_id: int) -> None:
        GUARDA.exigir(contexto, self.CONTATO)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            contato = _contato_vivo(repositorio, contato_id)
            telefones = [t for t in repositorio.telefones(contato.paciente_id) if t.contato_id == contato_id]
            repositorio.remover_contato(contato_id)
            for telefone in telefones:
                self._auditoria.registrar(
                    uow, contexto, self.TELEFONE, "telefone", str(telefone.id), _telefone_auditado(telefone, None)
                )
            alteracoes = _mudancas(
                ("paciente_id", contato.paciente_id, None), ("nome", contato.nome, None),
                ("parentesco", contato.parentesco, None),
            )  # fmt: skip
            self._auditoria.registrar(uow, contexto, self.CONTATO, "contato", str(contato_id), alteracoes)

        self._executar(operacao)

    # ---------------------------------------------------------------- telefones
    def incluir_telefone(
        self,
        contexto: Contexto,
        paciente_id: int,
        ddd: str,
        numero: str,
        tipo: TipoTelefone,
        contato_id: int | None = None,
    ) -> int:
        GUARDA.exigir(contexto, self.TELEFONE)
        ddd_limpo, numero_limpo = validar_telefone(ddd, numero, tipo)
        dono_paciente = paciente_id if contato_id is None else None  # INV-12: um dono só

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioPaciente)
            _paciente_vivo(repositorio, paciente_id)
            if contato_id is not None:
                contato = repositorio.contato(contato_id)
                if contato is None or contato.paciente_id != paciente_id:
                    raise NaoEncontrado()
            mesmo_dono = (
                t
                for t in repositorio.telefones(paciente_id)
                if (t.paciente_id, t.contato_id) == (dono_paciente, contato_id)
            )
            if any((t.ddd, t.numero) == (ddd_limpo, numero_limpo) for t in mesmo_dono):
                raise RegraViolada("telefone.repetido")
            telefone_id = repositorio.criar_telefone(dono_paciente, contato_id, ddd_limpo, numero_limpo, tipo.value)
            novo = TelefoneGravado(telefone_id, dono_paciente, contato_id, ddd_limpo, numero_limpo, tipo.value)
            self._auditoria.registrar(
                uow, contexto, self.TELEFONE, "telefone", str(telefone_id), _telefone_auditado(None, novo)
            )
            return telefone_id

        return self._executar(operacao)

    def alterar_telefone(self, contexto: Contexto, telefone_id: int, ddd: str, numero: str, tipo: TipoTelefone) -> None:
        GUARDA.exigir(contexto, self.TELEFONE)
        ddd_limpo, numero_limpo = validar_telefone(ddd, numero, tipo)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            telefone = _telefone_vivo(repositorio, telefone_id)
            alteracoes = _mudancas(
                ("ddd", telefone.ddd, ddd_limpo), ("numero", telefone.numero, numero_limpo),
                ("tipo", telefone.tipo, tipo.value),
            )  # fmt: skip
            if not alteracoes:
                return  # DD-10
            repositorio.alterar_telefone(telefone_id, ddd_limpo, numero_limpo, tipo.value)
            self._auditoria.registrar(uow, contexto, self.TELEFONE, "telefone", str(telefone_id), alteracoes)

        self._executar(operacao)

    def remover_telefone(self, contexto: Contexto, telefone_id: int) -> None:
        GUARDA.exigir(contexto, self.TELEFONE)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioPaciente)
            telefone = _telefone_vivo(repositorio, telefone_id)
            repositorio.remover_telefone(telefone_id)
            self._auditoria.registrar(
                uow, contexto, self.TELEFONE, "telefone", str(telefone_id), _telefone_auditado(telefone, None)
            )

        self._executar(operacao)


def _contato_vivo(repositorio: RepositorioPaciente, contato_id: int) -> ContatoGravado:
    """O contato, com o paciente dele travado e vivo."""
    contato = repositorio.contato(contato_id)
    if contato is None:
        raise NaoEncontrado()
    _paciente_vivo(repositorio, contato.paciente_id)
    return contato


def _telefone_vivo(repositorio: RepositorioPaciente, telefone_id: int) -> TelefoneGravado:
    """O telefone, com o paciente dono (direto ou pelo contato) travado e vivo."""
    telefone = repositorio.telefone(telefone_id)
    if telefone is None:
        raise NaoEncontrado()
    if telefone.paciente_id is not None:
        _paciente_vivo(repositorio, telefone.paciente_id)
    elif telefone.contato_id is not None:
        _contato_vivo(repositorio, telefone.contato_id)
    return telefone


class ServicoCep:
    """Implementa o CepService do contrato: a consulta do preenchimento, com o município resolvido na tabela do
    IBGE (pelo código, ou pelo nome e pela UF quando a fonte não traz o código)."""

    def __init__(self, executar: ExecutorDeOperacao, referencias: Referencias, provedor: ProvedorCep) -> None:
        self._executar = executar
        self._referencias = referencias
        self._provedor = provedor

    def consultar(self, contexto: Contexto, cep: str) -> EnderecoSugerido | None:
        GUARDA.exigir(contexto, "cadastro.cep.consultar")
        numero = digitos(cep, "cep.invalido")
        if numero is None or len(numero) != 8:
            raise RegraViolada("cep.invalido")
        endereco = self._provedor.consultar(numero)
        if endereco is None:
            return None
        municipio = self._executar(lambda uow: self._municipio(uow, endereco))
        return EnderecoSugerido(numero, endereco.logradouro, endereco.bairro, municipio)

    def _municipio(self, uow: UnidadeDeTrabalho, endereco: EnderecoCep) -> Municipio | None:
        if endereco.municipio_ibge is not None:
            return self._referencias.municipio(uow, endereco.municipio_ibge)
        if endereco.municipio_nome is None or endereco.uf is None:
            return None
        nome = " ".join(sem_acento(endereco.municipio_nome).casefold().split())
        try:
            candidatos = self._referencias.buscar_municipios(uow, endereco.municipio_nome, endereco.uf)
        except RegraViolada:
            return None  # UF que a tabela não conhece
        return next((m for m in candidatos if " ".join(sem_acento(m.nome).casefold().split()) == nome), None)


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
