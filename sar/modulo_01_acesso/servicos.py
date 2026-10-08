"""Serviços do MOD-01 (DDS §5)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta

from sar.modulo_01_acesso.contrato import (
    AuditService,
    AvisoDiagnostico,
    AvisoSimples,
    CodigoIntegridade,
    Conferencia,
    CredencialInvalida,
    PermissionGuard,
    ResultadoVerificacao,
    SessaoAberta,
    SessaoEncerrada,
    TermoPendente,
    TrocaDeSenhaExigida,
    UsuarioCriado,
    UsuarioResumo,
)
from sar.modulo_01_acesso.regras import (
    cinco_anos_antes,
    codigo_do_hash,
    minutos_de_bloqueio,
    normalizar_codigo,
    senha_provisoria,
    validar_login,
    validar_nome,
    validar_senha,
    verificar_elos,
)
from sar.modulo_01_acesso.senhas import Hasher, hash_token, novo_token
from sar.modulo_08_dados.canonico import HASH_INICIAL, serializar_alteracoes
from sar.modulo_08_dados.interfaces.sessoes import RepositorioSessao
from sar.modulo_08_dados.interfaces.trilha import RepositorioExpurgo, RepositorioTrilha
from sar.modulo_08_dados.interfaces.usuarios import DadosUsuario, RepositorioUsuario
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.erros import AcessoNegado, ConflitoDeVersao, ErroSAR, NaoEncontrado, RegraViolada
from sar.nucleo.eventos import CadeiaDivergente, UsuarioInativado
from sar.nucleo.logs import campos_do_erro, novo_requisicao_id, requisicao_atual
from sar.nucleo.parametros import LeitorParametros
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


# ------------------------------------------------------------------ autenticação (DDS §5.2, DD-83)
@dataclass(frozen=True, slots=True)
class _Desfecho:
    """O que a operação decidiu. Falha também é gravada (contador, bloqueio, sessão encerrada e trilha): por isso
    a operação confirma e o erro só é levantado depois do commit."""

    sessao: SessaoAberta | None = None
    erro: type[ErroSAR] | None = None


def _inteiro(valor: object) -> int:
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise TypeError("parâmetro inteiro esperado")
    return valor


class ServicoAutenticacao:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        parametros: LeitorParametros,
        relogio: Relogio,
        hasher: Hasher,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._parametros = parametros
        self._relogio = relogio
        self._hasher = hasher

    def entrar(self, login: str, senha: str, origem: str, nova_senha: str | None = None) -> SessaoAberta:
        """CredencialInvalida (sempre a mesma), TermoPendente, TrocaDeSenhaExigida ou RegraViolada (nova senha
        fraca). Abre a sessão na mesma transação e encerra a anterior do usuário (P-02, DEC-63)."""
        agora = self._relogio.agora()
        limite = _inteiro(self._parametros.valor("login_tentativas"))
        inicial = _inteiro(self._parametros.valor("login_bloqueio_inicial"))
        teto = _inteiro(self._parametros.valor("login_bloqueio_teto"))
        requisicao = requisicao_atual() or novo_requisicao_id()

        def falha(uow: UnidadeDeTrabalho, contexto: Contexto, motivo: str, erro: type[ErroSAR]) -> _Desfecho:
            entidade_id = str(contexto.usuario_id) if contexto.usuario_id else None
            self._auditoria.registrar(uow, contexto, "acesso.sessao.entrar", "usuario", entidade_id, motivo=motivo)
            return _Desfecho(erro=erro)

        def operacao(uow: UnidadeDeTrabalho) -> _Desfecho:
            usuarios = uow.repositorio(RepositorioUsuario)
            usuario = usuarios.por_login(login.strip())
            # Uma verificação bcrypt em todo caminho: o tempo não revela se o login existe (§5.2).
            confere = self._hasher.conferir(senha, usuario.senha_hash if usuario else None)
            if usuario is None:
                # O que foi digitado no login não vai para a trilha: pode ser uma senha digitada no campo errado.
                anonimo = Contexto.sistema(origem, agora, requisicao)
                return falha(uow, anonimo, "falha.login_inexistente", CredencialInvalida)
            contexto = Contexto(usuario.id, Perfil(usuario.perfil), None, origem, agora, requisicao)
            if not usuario.ativo:
                return falha(uow, contexto, "falha.inativo", CredencialInvalida)
            if usuario.bloqueado_ate is not None and agora < usuario.bloqueado_ate:
                return falha(uow, contexto, "falha.bloqueado", CredencialInvalida)  # não conta nova falha
            if not confere:
                tentativas = usuarios.incrementar_falhas(usuario.id)
                minutos = minutos_de_bloqueio(tentativas, limite, inicial, teto)
                usuarios.definir_bloqueio(usuario.id, agora + timedelta(minutes=minutos) if minutos else None)
                motivo = f"falha.senha_incorreta; bloqueio de {minutos} min" if minutos else "falha.senha_incorreta"
                return falha(uow, contexto, motivo, CredencialInvalida)
            if usuario.tentativas_falhas or usuario.bloqueado_ate:
                usuarios.zerar_falhas(usuario.id)
            if usuario.termo_ciencia_em is None:
                return falha(uow, contexto, "falha.termo_pendente", TermoPendente)  # DEC-47
            if usuario.deve_trocar_senha:
                if nova_senha is None:
                    return falha(uow, contexto, "falha.troca_exigida", TrocaDeSenhaExigida)
                self._gravar_nova_senha(uow, contexto, usuario, nova_senha)
            return _Desfecho(sessao=self._abrir_sessao(uow, contexto, usuario.nome))

        desfecho = self._executar(operacao)
        if desfecho.erro is not None:
            raise desfecho.erro()
        if desfecho.sessao is None:  # sem erro, a operação sempre devolve a sessão
            raise RuntimeError("entrada sem desfecho")
        return desfecho.sessao

    def _abrir_sessao(self, uow: UnidadeDeTrabalho, contexto: Contexto, nome: str) -> SessaoAberta:
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise AcessoNegado()
        uow.repositorio(RepositorioUsuario).travar(usuario_id)  # duas entradas simultâneas se serializam
        sessoes = uow.repositorio(RepositorioSessao)
        for anterior in sessoes.encerrar_do_usuario(usuario_id, contexto.instante, "novo_login"):  # P-02
            fim = replace(contexto, sessao_id=anterior)
            self._auditoria.registrar(uow, fim, "acesso.sessao.sair", "usuario", str(usuario_id), motivo="novo_login")
        token = novo_token()  # identificador novo a cada entrada (DD-19)
        sessao_id = sessoes.criar(hash_token(token), usuario_id, contexto.origem, contexto.instante)
        aberto = replace(contexto, sessao_id=sessao_id)
        self._auditoria.registrar(uow, aberto, "acesso.sessao.entrar", "usuario", str(usuario_id))
        return SessaoAberta(token, aberto, nome)

    def sair(self, contexto: Contexto) -> None:
        GUARDA.exigir(contexto, "acesso.sessao.sair")
        sessao_id = contexto.sessao_id
        if sessao_id is None:
            raise AcessoNegado()

        def operacao(uow: UnidadeDeTrabalho) -> None:
            uow.repositorio(RepositorioSessao).encerrar(sessao_id, contexto.instante, "saida")
            self._auditoria.registrar(
                uow, contexto, "acesso.sessao.sair", "usuario", str(contexto.usuario_id), motivo="saida"
            )

        self._executar(operacao)

    def trocar_propria_senha(self, contexto: Contexto, senha_atual: str, nova_senha: str) -> None:
        GUARDA.exigir(contexto, "acesso.senha.trocar_propria")
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise AcessoNegado()

        def operacao(uow: UnidadeDeTrabalho) -> bool:
            usuario = uow.repositorio(RepositorioUsuario).por_id(usuario_id)
            if usuario is None or not self._hasher.conferir(senha_atual, usuario.senha_hash):
                return False
            self._gravar_nova_senha(uow, contexto, usuario, nova_senha)
            return True

        if not self._executar(operacao):
            raise CredencialInvalida()

    def _gravar_nova_senha(self, uow: UnidadeDeTrabalho, contexto: Contexto, usuario: DadosUsuario, nova: str) -> None:
        validar_senha(nova, usuario.login, usuario.nome)  # DD-83
        if self._hasher.conferir(nova, usuario.senha_hash):
            raise RegraViolada("senha.igual_a_atual")
        uow.repositorio(RepositorioUsuario).trocar_senha(usuario.id, self._hasher.gerar(nova), deve_trocar=False)
        # "Sim, sem valores" (§4.1): nem a senha nem o hash entram na trilha.
        self._auditoria.registrar(uow, contexto, "acesso.senha.trocar_propria", "usuario", str(usuario.id))


# ------------------------------------------------------------------ sessão (DD-05, DD-19, P-02)
@dataclass(frozen=True, slots=True)
class _Validacao:
    contexto: Contexto | None = None
    motivo: str | None = None  # por que a sessão não vale; None com contexto None = token desconhecido


class GerenciadorSessao:
    def __init__(
        self, executar: ExecutorDeOperacao, auditoria: AuditService, parametros: LeitorParametros, relogio: Relogio
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._parametros = parametros
        self._relogio = relogio

    def validar(self, token: str, origem: str, automatica: bool = False) -> Contexto:
        agora = self._relogio.agora()
        inatividade = timedelta(minutes=_inteiro(self._parametros.valor("sessao_inatividade")))
        duracao_maxima = timedelta(hours=_inteiro(self._parametros.valor("sessao_duracao_maxima")))
        requisicao = requisicao_atual() or novo_requisicao_id()

        def operacao(uow: UnidadeDeTrabalho) -> _Validacao:
            sessoes = uow.repositorio(RepositorioSessao)
            sessao = sessoes.por_token_hash(hash_token(token))
            if sessao is None:
                return _Validacao()
            if sessao.encerrada_em is not None:
                return _Validacao(motivo=sessao.motivo_encerramento)
            # O usuário é lido a cada requisição: perfil alterado vale na hora, e inativado não age mais.
            usuario = uow.repositorio(RepositorioUsuario).por_id(sessao.usuario_id)
            if usuario is None:
                return _Validacao()
            contexto = Contexto(usuario.id, Perfil(usuario.perfil), sessao.id, origem, agora, requisicao)
            motivo = None
            if not usuario.ativo:
                motivo = "inativacao"
            elif agora - sessao.ultimo_acesso > inatividade:
                motivo = "inatividade"  # DD-19, QAS-09: a próxima ação exige nova entrada
            elif agora - sessao.criada_em > duracao_maxima:
                motivo = "limite"
            if motivo is not None:
                sessoes.encerrar(sessao.id, agora, motivo)
                self._auditoria.registrar(
                    uow, contexto, "acesso.sessao.sair", "usuario", str(usuario.id), motivo=motivo
                )
                return _Validacao(motivo=motivo)
            if not automatica:
                sessoes.tocar(sessao.id, agora)  # a atualização automática da tela não conta (DD-57)
            return _Validacao(contexto=contexto)

        validacao = self._executar(operacao)
        if validacao.contexto is None:
            raise SessaoEncerrada(validacao.motivo)
        return validacao.contexto


def manipulador_encerrar_sessoes(relogio: Relogio) -> Callable[[UnidadeDeTrabalho, UsuarioInativado], None]:
    """Consumidor de UsuarioInativado (DDS §3.11): as sessões do usuário acabam na mesma transação."""

    def encerrar(uow: UnidadeDeTrabalho, evento: UsuarioInativado) -> None:
        uow.repositorio(RepositorioSessao).encerrar_do_usuario(evento.usuario_id, relogio.agora(), "inativacao")

    return encerrar


# ------------------------------------------------------------------ usuários (DDS §5.1, §4.1, DD-85)
PERFIS_DE_PESSOA = frozenset(p for p in Perfil if p is not Perfil.SISTEMA)


def _resumo(u: DadosUsuario) -> UsuarioResumo:
    return UsuarioResumo(
        u.id, u.nome, u.login, Perfil(u.perfil), u.ativo, u.termo_ciencia_em, u.deve_trocar_senha, u.bloqueado_ate,
        u.versao,
    )  # fmt: skip


class ServicoUsuarios:
    def __init__(self, executar: ExecutorDeOperacao, auditoria: AuditService, hasher: Hasher) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._hasher = hasher

    def consultar(self, contexto: Contexto) -> list[UsuarioResumo]:
        GUARDA.exigir(contexto, "acesso.usuario.consultar")
        return self._executar(lambda uow: [_resumo(u) for u in uow.repositorio(RepositorioUsuario).listar()])

    def criar(self, contexto: Contexto, nome: str, login: str, perfil: Perfil) -> UsuarioCriado:
        GUARDA.exigir(contexto, "acesso.usuario.criar")
        return self._criar(contexto, nome, login, perfil, com_termo=False)

    def criar_primeiro_ti(self, contexto: Contexto, nome: str, login: str) -> UsuarioCriado:
        """Linha de comando da implantação (DD-85): só pelo contexto de sistema e só quando não há TI ativo.
        O termo entra registrado, porque não há outro TI para registrá-lo; quem roda o comando o declara."""
        if not contexto.e_sistema:
            raise AcessoNegado()

        def ha_ti_ativo(uow: UnidadeDeTrabalho) -> bool:
            return any(u.ativo and u.perfil == Perfil.TI.value for u in uow.repositorio(RepositorioUsuario).listar())

        if self._executar(ha_ti_ativo):
            raise RegraViolada("usuario.ja_existe_ti_ativo")
        return self._criar(contexto, nome, login, Perfil.TI, com_termo=True)

    def criar_para_desenvolvimento(self, contexto: Contexto, nome: str, login: str) -> UsuarioCriado:
        """Superusuário de desenvolvimento (DD-85). Quem garante o ambiente é a linha de comando."""
        if not contexto.e_sistema:
            raise AcessoNegado()
        return self._criar(contexto, nome, login, Perfil.ADMINISTRACAO, com_termo=True)

    def _criar(self, contexto: Contexto, nome: str, login: str, perfil: Perfil, com_termo: bool) -> UsuarioCriado:
        nome, login = validar_nome(nome), validar_login(login)
        if perfil not in PERFIS_DE_PESSOA:
            raise RegraViolada("usuario.perfil")
        provisoria = senha_provisoria(login, nome)
        senha_hash = self._hasher.gerar(provisoria)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            usuarios = uow.repositorio(RepositorioUsuario)
            if usuarios.por_login(login) is not None:
                raise RegraViolada("usuario.login_repetido")
            termo = contexto.instante if com_termo else None
            usuario_id = usuarios.criar(nome, login, senha_hash, perfil.value, contexto.instante, termo)
            alteracoes: dict[str, tuple[object, object]] = {
                "nome": (None, nome), "login": (None, login), "perfil": (None, perfil.value)
            }  # fmt: skip
            if termo is not None:
                alteracoes["termo_ciencia_em"] = (None, termo)
            self._auditoria.registrar(uow, contexto, "acesso.usuario.criar", "usuario", str(usuario_id), alteracoes)
            return usuario_id

        try:
            return UsuarioCriado(self._executar(operacao), provisoria)
        except Exception as erro:
            if campos_do_erro(erro).get("restricao") == "uq_usuario__login":  # outro TI criou ao mesmo tempo
                raise RegraViolada("usuario.login_repetido") from None
            raise

    def _alterar(
        self,
        contexto: Contexto,
        operacao_catalogo: str,
        usuario_id: int,
        versao: int,
        mudar: Callable[[UnidadeDeTrabalho, DadosUsuario], dict[str, tuple[object, object]] | None],
    ) -> None:
        """Esqueleto das alterações da tela do TI: permissão, usuário existente, versão (DD-17) e auditoria."""
        GUARDA.exigir(contexto, operacao_catalogo)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            usuario = uow.repositorio(RepositorioUsuario).por_id(usuario_id)
            if usuario is None:
                raise NaoEncontrado()
            if usuario.versao != versao:
                raise ConflitoDeVersao(None, None)
            alteracoes = mudar(uow, usuario)
            if alteracoes is None:
                raise ConflitoDeVersao(None, None)  # a gravação condicionada à versão não pegou nenhuma linha
            self._auditoria.registrar(uow, contexto, operacao_catalogo, "usuario", str(usuario_id), alteracoes)

        self._executar(operacao)

    def alterar_perfil(self, contexto: Contexto, usuario_id: int, versao: int, perfil: Perfil) -> None:
        if perfil not in PERFIS_DE_PESSOA:
            raise RegraViolada("usuario.perfil")

        def mudar(uow: UnidadeDeTrabalho, u: DadosUsuario) -> dict[str, tuple[object, object]] | None:
            if u.perfil == perfil.value:
                raise RegraViolada("usuario.perfil_igual")
            if not uow.repositorio(RepositorioUsuario).alterar_perfil(u.id, versao, perfil.value):
                return None
            return {"perfil": (u.perfil, perfil.value)}

        self._alterar(contexto, "acesso.usuario.alterar_perfil", usuario_id, versao, mudar)

    def inativar(self, contexto: Contexto, usuario_id: int, versao: int) -> None:
        def mudar(uow: UnidadeDeTrabalho, u: DadosUsuario) -> dict[str, tuple[object, object]] | None:
            if not u.ativo:
                raise RegraViolada("usuario.ja_inativo")
            if not uow.repositorio(RepositorioUsuario).definir_ativo(u.id, versao, False):
                return None
            uow.publicar(UsuarioInativado(usuario_id=u.id))  # encerra as sessões dele (§3.11)
            return {"ativo": (True, False)}

        self._alterar(contexto, "acesso.usuario.inativar", usuario_id, versao, mudar)

    def reativar(self, contexto: Contexto, usuario_id: int, versao: int) -> None:
        def mudar(uow: UnidadeDeTrabalho, u: DadosUsuario) -> dict[str, tuple[object, object]] | None:
            if u.ativo:
                raise RegraViolada("usuario.ja_ativo")
            if not uow.repositorio(RepositorioUsuario).definir_ativo(u.id, versao, True):
                return None
            return {"ativo": (False, True)}

        self._alterar(contexto, "acesso.usuario.reativar", usuario_id, versao, mudar)

    def redefinir_senha(self, contexto: Contexto, usuario_id: int, versao: int) -> str:
        provisoria: list[str] = []

        def mudar(uow: UnidadeDeTrabalho, u: DadosUsuario) -> dict[str, tuple[object, object]] | None:
            nova = senha_provisoria(u.login, u.nome)
            if not uow.repositorio(RepositorioUsuario).redefinir_senha(u.id, versao, self._hasher.gerar(nova)):
                return None
            provisoria.append(nova)
            return {"deve_trocar_senha": (u.deve_trocar_senha, True)}  # nem a senha nem o hash entram na trilha

        self._alterar(contexto, "acesso.usuario.redefinir_senha", usuario_id, versao, mudar)
        return provisoria[-1]

    def registrar_termo(self, contexto: Contexto, usuario_id: int, versao: int) -> None:
        def mudar(uow: UnidadeDeTrabalho, u: DadosUsuario) -> dict[str, tuple[object, object]] | None:
            if u.termo_ciencia_em is not None:
                raise RegraViolada("usuario.termo_ja_registrado")
            if not uow.repositorio(RepositorioUsuario).registrar_termo(u.id, versao, contexto.instante):
                return None
            return {"termo_ciencia_em": (None, contexto.instante)}

        self._alterar(contexto, "acesso.usuario.registrar_termo_ciencia", usuario_id, versao, mudar)
