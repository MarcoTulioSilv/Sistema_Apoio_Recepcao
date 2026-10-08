"""Linha de comando `sar` (DDS §12.1).

  sar migrar [alvo]          aplica as migrações até o alvo (padrão: head), como sar_migracao
  sar reverter alvo          desfaz até o alvo; só antes do go-live (DD-60)
  sar criar-usuarios-banco   cria sar_web, sar_worker e sar_expurgo com as senhas dos segredos (DD-58)
  sar verificar-cadeia       verifica a trilha de auditoria como o job diário (§13.1), pelo usuário do worker
  sar criar-usuario-ti       primeiro TI da implantação, quando não há TI ativo (DD-85)
  sar criar-superusuario     superusuário, só em desenvolvimento (DD-85)

Fica fora dos módulos porque junta comandos do MOD-08 e do MOD-01, como a raiz de composição.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.exc import DBAPIError

from sar.composicao import Ambiente, ambiente_atual, compor_auditoria, montar_barramento, montar_executor
from sar.modulo_01_acesso.contrato import UsuarioCriado
from sar.modulo_01_acesso.senhas import Hasher
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoUsuarios
from sar.modulo_08_dados import cli as banco
from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.modulo_08_dados.erros_banco import anotar_restricao
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import RegraViolada
from sar.nucleo.logs import campos_do_erro, configurar, iniciar_requisicao


def verificar_cadeia() -> int:
    engine = criar_engine(ConfigBanco.do_ambiente("sar_worker"))
    try:
        contexto = Contexto.sistema("cli.verificar_cadeia", RelogioSistema().agora())
        resultado = compor_auditoria(engine).verificar_cadeia(contexto)
    finally:
        engine.dispose()
    if resultado.integra:
        print(f"Cadeia íntegra: {resultado.verificados} registro(s) verificado(s); âncora registrada.")
        return 0
    print(
        f"Divergência no registro {resultado.primeiro_divergente_id} ({resultado.motivo}); "
        f"{resultado.verificados} registro(s) íntegro(s) antes dele. Aviso de integridade aberto.",
        file=sys.stderr,
    )
    return 1


def _criar_usuario(comando: str, nome: str, login: str) -> UsuarioCriado:
    """Pelo mesmo serviço da tela, com o usuário de banco da web e o contexto de sistema (auditado)."""
    relogio = RelogioSistema()
    engine = criar_engine(ConfigBanco.do_ambiente("sar_web"))
    try:
        servico = ServicoUsuarios(montar_executor(engine, montar_barramento(relogio)), ServicoAuditoria(), Hasher())
        contexto = Contexto.sistema(f"cli.{comando}", relogio.agora())
        if comando == "criar_usuario_ti":
            return servico.criar_primeiro_ti(contexto, nome, login)
        return servico.criar_para_desenvolvimento(contexto, nome, login)
    finally:
        engine.dispose()


def criar_usuario_ti(nome: str, login: str, termo_assinado: bool) -> int:
    if not termo_assinado:
        print(
            "Recusado: confirme com --termo-assinado que o termo de ciência de uso foi assinado (DEC-47).",
            file=sys.stderr,
        )
        return 1
    criado = _criar_usuario("criar_usuario_ti", nome, login)
    print(
        f"Usuário TI criado (id {criado.id}). Senha provisória, a trocar na primeira entrada: {criado.senha_provisoria}"
    )
    return 0


def criar_superusuario(nome: str, login: str) -> int:
    if ambiente_atual() is not Ambiente.DESENVOLVIMENTO:
        print("Recusado: superusuário só existe com SAR_AMBIENTE=desenvolvimento (DD-85).", file=sys.stderr)
        return 1
    criado = _criar_usuario("criar_superusuario", nome, login)
    print(f"Superusuário criado (id {criado.id}).")
    print(f"Senha provisória, a trocar na primeira entrada: {criado.senha_provisoria}")
    print(f"Para trocar de perfil pela tela, acrescente {login} a SAR_SUPERUSUARIOS.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sar", description="Linha de comando do SAR")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("migrar", help="aplica as migrações")
    p.add_argument("alvo", nargs="?", default="head")
    p = sub.add_parser("reverter", help="desfaz migrações (só antes do go-live)")
    p.add_argument("alvo")
    p = sub.add_parser("criar-usuarios-banco", help="cria os usuários por processo")
    p.add_argument("--admin", default="root", help="usuário com privilégio de criar usuários")
    p.add_argument("--segredo-admin", default="mysql_root", help="segredo com a senha do administrador")
    sub.add_parser("verificar-cadeia", help="verifica a trilha de auditoria e registra a âncora")
    p = sub.add_parser("criar-usuario-ti", help="primeiro TI da implantação")
    p.add_argument("--nome", required=True)
    p.add_argument("--login", required=True)
    p.add_argument("--termo-assinado", action="store_true", help="o termo de ciência de uso foi assinado")
    p = sub.add_parser("criar-superusuario", help="superusuário de desenvolvimento")
    p.add_argument("--nome", required=True)
    p.add_argument("--login", required=True)
    args = parser.parse_args(argv)
    configurar("cli")
    iniciar_requisicao()  # liga as linhas de log e a auditoria desta execução (DD-81)

    try:
        if args.comando == "migrar":
            banco.migrar(args.alvo)
        elif args.comando == "reverter":
            banco.reverter(args.alvo)
        elif args.comando == "criar-usuarios-banco":
            banco.criar_usuarios_banco(args.admin, args.segredo_admin)
        elif args.comando == "criar-usuario-ti":
            return criar_usuario_ti(args.nome, args.login, args.termo_assinado)
        elif args.comando == "criar-superusuario":
            return criar_superusuario(args.nome, args.login)
        else:
            return verificar_cadeia()
    except Exception as erro:
        if isinstance(erro, DBAPIError):
            anotar_restricao(erro)
        # Sem traceback: o texto de um erro de banco traz o SQL, que aqui pode conter senha (DD-81).
        detalhe = " ".join(f"{campo}={valor}" for campo, valor in campos_do_erro(erro).items())
        codigo = f" ({erro.codigo})" if isinstance(erro, RegraViolada) else ""
        print(f"Falhou: {detalhe}{codigo}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
