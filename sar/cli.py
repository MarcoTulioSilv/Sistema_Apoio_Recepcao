"""Linha de comando `sar` (DDS §12.1).

  sar migrar [alvo]          aplica as migrações até o alvo (padrão: head), como sar_migracao
  sar reverter alvo          desfaz até o alvo; só antes do go-live (DD-60)
  sar criar-usuarios-banco   cria sar_web, sar_worker e sar_expurgo com as senhas dos segredos (DD-58)
  sar verificar-cadeia       verifica a trilha de auditoria como o job diário (§13.1), pelo usuário do worker

Fica fora dos módulos porque junta comandos do MOD-08 e do MOD-01, como a raiz de composição.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.exc import DBAPIError

from sar.composicao import compor_auditoria
from sar.modulo_08_dados import cli as banco
from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.modulo_08_dados.erros_banco import anotar_restricao
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.nucleo.contexto import Contexto
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
        else:
            return verificar_cadeia()
    except Exception as erro:
        if isinstance(erro, DBAPIError):
            anotar_restricao(erro)
        # Sem traceback: o texto de um erro de banco traz o SQL, que aqui pode conter senha (DD-81).
        detalhe = " ".join(f"{campo}={valor}" for campo, valor in campos_do_erro(erro).items())
        print(f"Falhou: {detalhe}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
