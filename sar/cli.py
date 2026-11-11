"""Linha de comando `sar` (DDS §12.1).

  sar migrar [alvo]          aplica as migrações até o alvo (padrão: head), como sar_migracao
  sar reverter alvo          desfaz até o alvo; só antes do go-live (DD-60)
  sar criar-usuarios-banco   cria sar_web, sar_worker e sar_expurgo com as senhas dos segredos (DD-58)
  sar verificar-cadeia       verifica a trilha de auditoria como o job diário (§13.1), pelo usuário do worker
  sar criar-usuario-ti       primeiro TI da implantação, quando não há TI ativo (DD-85)
  sar criar-superusuario     superusuário, só em desenvolvimento (DD-85)
  sar worker                 consumidor da fila de ingestão (DD-63) e agendador dos jobs (§13.1), até Ctrl+C
  sar job listar             último sucesso e atraso de cada job do catálogo (§13.1)
  sar job executar NOME      execução manual de um job, pelo TI no servidor (DD-112)
  sar job registrar NOME     registro do backup e da cópia para o pen drive pelos scripts do servidor (DD-62)
  sar documentos-revarrer    revarredura antimalware do acervo (SEG-22); --minutos e --depois-de para retomar
  sar documentos-hash        conferência de hash do acervo (SEG-15, P-19); mesmas opções
  sar documentos-orfaos      remove do cofre arquivo sem documento (DD-37)
  sar carga simular PASTA    carga inicial em simulação, pelo TI, com login e senha (DD-65, DD-66, DD-113)
  sar carga efetivar PASTA   a carga de verdade, uma vez só; o terminal mostra só contagens

Fica fora dos módulos porque junta comandos do MOD-08 e do MOD-01, como a raiz de composição.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import DBAPIError

from sar.composicao import (
    Ambiente,
    Worker,
    ambiente_atual,
    antimalware_do_ambiente,
    compor_agendamento,
    compor_auditoria,
    compor_carga,
    compor_registro,
    compor_rotinas,
    montar_barramento,
    montar_executor,
    pastas_do_ambiente,
)
from sar.modulo_01_acesso.contrato import CredencialInvalida, TermoPendente, TrocaDeSenhaExigida, UsuarioCriado
from sar.modulo_01_acesso.senhas import Hasher
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoUsuarios
from sar.modulo_08_dados import cli as banco
from sar.modulo_08_dados.banco import ConfigBanco, criar_engine
from sar.modulo_08_dados.cifra import carregar_chave_mestra
from sar.modulo_08_dados.erros_banco import anotar_restricao
from sar.modulo_08_dados.relogio import FUSO_CLINICA, RelogioSistema
from sar.modulo_09_agendamento.contrato import Execucao, JobDesconhecido, JobEmAndamento, Resultado
from sar.modulo_10_carga.contrato import ResumoCarga
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, ConfiguracaoInvalida, RegraViolada
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
    gravado = login.strip().lower()  # o login fica em minúsculas, como a tela grava
    print(f"Login gravado: {gravado}. Para trocar de perfil pela tela, inclua-o em SAR_SUPERUSUARIOS antes de")
    print(f'subir o servidor, exatamente assim. PowerShell: $env:SAR_SUPERUSUARIOS = "{gravado}"')
    return 0


def _com_worker[T](tarefa: Callable[[Worker], T]) -> T:
    """Monta o worker pelos usuários de banco dele e do expurgo (DD-58), com o clamd do ambiente."""
    pastas = pastas_do_ambiente()  # a configuração do terminal primeiro: sem ela, nem vale ler os segredos
    engine = criar_engine(ConfigBanco.do_ambiente("sar_worker"))
    try:
        engine_expurgo = criar_engine(ConfigBanco.do_ambiente("sar_expurgo"))
        try:
            montado = compor_agendamento(engine, engine_expurgo, carregar_chave_mestra(), pastas,
                                         antimalware_do_ambiente())  # fmt: skip
            return tarefa(montado)
        finally:
            engine_expurgo.dispose()
    finally:
        engine.dispose()


def worker(parar: threading.Event | None = None) -> int:
    """O laço da fila no processo principal e o agendador nas linhas dele, até Ctrl+C."""
    parar = parar or threading.Event()

    def rodar(w: Worker) -> int:
        imediatos = w.agendador.iniciar()
        try:
            print(f"Worker no ar: fila de ingestão e agendador ({len(w.agendamento.jobs)} jobs). Ctrl+C para parar.",
                  flush=True)  # fmt: skip
            if imediatos:
                print(f"Perderam o horário e rodam agora: {', '.join(imediatos)}.", flush=True)
            w.processador.rodar(parar)
        except KeyboardInterrupt:
            parar.set()
        finally:
            w.agendador.parar()
        return 0

    return _com_worker(rodar)


def _local(instante: datetime | None) -> str:
    return f"{instante.astimezone(FUSO_CLINICA):%d/%m/%Y %H:%M}" if instante else "nunca"


def _linha(execucao: Execucao) -> str:
    parcial = ", parou no limite de horário" if execucao.parcial else ""
    erro = f", erro {execucao.resumo_erro}" if execucao.resumo_erro else ""
    itens = f", {execucao.itens} item(ns)" if execucao.itens is not None else ""
    return f"{execucao.job}: {execucao.resultado.value} em {_local(execucao.inicio)}{itens}{parcial}{erro}"


def job_listar() -> int:
    """1 se algum job estiver atrasado, para o script de monitoramento do servidor poder usar."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_worker"))
    try:
        situacao = compor_registro(engine).situacao_do_sistema(RelogioSistema().agora())
    finally:
        engine.dispose()
    for job in situacao:
        marca = "ATRASADO" if job.atrasado else "em dia"
        print(f"{job.nome:22} {marca:9} último sucesso: {_local(job.ultimo_sucesso):16}  ({job.quando})")
    return 1 if any(j.atrasado for j in situacao) else 0


def job_executar(nome: str, minutos: float | None) -> int:
    def executar(w: Worker) -> int:
        contexto = Contexto.sistema(f"cli.job.{nome}", RelogioSistema().agora())
        try:
            feita = w.agendamento.executar(contexto, nome, minutos)
        except JobDesconhecido:
            print(f"Job desconhecido: {nome}. Veja os nomes com: sar job listar", file=sys.stderr)
            return 1
        except JobEmAndamento:
            print(f"{nome} já está rodando noutro processo.", file=sys.stderr)
            return 1
        except AcessoNegado:
            print(f"{nome} não tem execução manual (DDS §13.1).", file=sys.stderr)
            return 1
        print(_linha(feita))
        return 0 if feita.resultado is not Resultado.FALHA else 1

    return _com_worker(executar)


def job_registrar(nome: str, resultado: str, inicio: str, fim: str, itens: int | None) -> int:
    """Pelo usuário de banco do worker, sem a chave mestra: o script do backup roda como o sistema (DD-62)."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_worker"))
    try:
        contexto = Contexto.sistema(f"cli.job.registrar.{nome}", RelogioSistema().agora())
        feita = compor_registro(engine).registrar_externo(contexto, nome, Resultado(resultado), _instante(inicio),
                                                          _instante(fim), itens)  # fmt: skip
    finally:
        engine.dispose()
    print(f"Registrado. {_linha(feita)}")
    return 0


def _instante(texto: str) -> datetime:
    """ISO 8601; sem fuso, é a hora da clínica (o date --iso-8601=seconds do servidor já traz o fuso)."""
    valor = datetime.fromisoformat(texto)
    return valor if valor.tzinfo is not None else valor.replace(tzinfo=FUSO_CLINICA)


def rotina_documentos(comando: str, depois_de: str | None, minutos: float | None) -> int:
    """As rotinas do acervo pelo usuário de banco do worker; o agendamento noturno chega com o MOD-09 (DD-41)."""
    engine = criar_engine(ConfigBanco.do_ambiente("sar_worker"))
    try:
        rotinas = compor_rotinas(engine, carregar_chave_mestra(), pastas_do_ambiente(), antimalware_do_ambiente())
        if comando == "documentos-orfaos":
            print(f"Arquivos órfãos removidos do cofre: {rotinas.remover_orfaos()}.")
            return 0
        segundos = minutos * 60 if minutos is not None else None
        rodar = rotinas.revarrer if comando == "documentos-revarrer" else rotinas.verificar_hashes
        resultado = rodar(depois_de, segundos)
    finally:
        engine.dispose()
    print(f"Documentos verificados: {resultado.verificados}; bloqueados: {len(resultado.bloqueados)}; "
          f"desbloqueados: {len(resultado.desbloqueados)}.")  # fmt: skip
    for documento_id in resultado.bloqueados:
        print(f"  bloqueado: {documento_id}")
    if resultado.cursor is not None:
        print(f"Parou no prazo. Para continuar: sar {comando} --depois-de {resultado.cursor}")
    return 1 if resultado.bloqueados else 0


ORIGEM_CARGA = "cli.carga"


def _linhas_da_carga(resumo: ResumoCarga) -> list[str]:
    """Só contagens e códigos, nunca dado de paciente (DD-65, RF-1004): é o que o TI vê."""
    c: dict[str, Any] = resumo.contagens
    p1, p4, p3 = c["p1"], c["p4"], c["p3"]
    linhas = [
        f"Carga em {resumo.modo.value} (lote {resumo.lote_id}). A conta fecha: {'sim' if c['fecha'] else 'NÃO'}.",
        f"  P1 endereços e telefones: {p1['linhas']} ficha(s) = {p1['importados']} importada(s) + "
        f"{p1['excecoes']} exceção(ões)",
        f"  P4 entradas: {p4['linhas']} linha(s) = {p4['ligadas']} ligada(s) a uma ficha + {p4['fora_da_base']} fora "
        f"da base + {p4['sem_prontuario']} sem prontuário",
        f"  P3 eventos: {p3['linhas']} linha(s) = {p3['casadas']} casada(s) com uma ficha + "
        f"{p3['sem_correspondencia']} sem correspondência",
        f"  CID descartado (ND-45): {c['cid_descartados']}",
    ]
    for titulo, chave in (("Exceções", "excecoes"), ("Avisos", "avisos")):
        if c[chave]:
            linhas.append(f"{titulo}, por código:")
            linhas.extend(f"  {codigo:32} {quantos}" for codigo, quantos in c[chave].items())
    linhas.append("O relatório com as linhas fica na aplicação, para a recepção e a administração (DD-65).")
    return linhas


def carga(acao: str, pasta: str, login: str, definitiva: bool) -> int:
    """O TI entra com login e senha, sem abrir sessão (DD-113); a operação roda com o perfil dele (§4.9)."""
    if acao == "efetivar" and not definitiva:
        print(
            "Recusado: a efetivação é única e não se desfaz (DD-66). Rode antes a simulação e, com o relatório "
            "aceito pela recepção, repita com --definitiva.",
            file=sys.stderr,
        )
        return 1
    senha = getpass.getpass(f"Senha de {login}: ")
    engine = criar_engine(ConfigBanco.do_ambiente("sar_web"))
    try:
        montado = compor_carga(engine, carregar_chave_mestra())
        try:
            contexto = montado.autenticacao.autenticar_terminal(login, senha, ORIGEM_CARGA)
        except CredencialInvalida, TermoPendente, TrocaDeSenhaExigida:
            print(
                "Recusado: login ou senha não conferem, ou o usuário precisa entrar antes pela tela.", file=sys.stderr
            )
            return 1
        try:
            rodar = montado.carga.simular if acao == "simular" else montado.carga.efetivar
            resumo = rodar(contexto, Path(pasta))
        except AcessoNegado:
            print("Recusado: a carga é do perfil TI (DDS §4.9).", file=sys.stderr)
            return 1
    finally:
        engine.dispose()
    for linha in _linhas_da_carga(resumo):
        print(linha)
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
    sub.add_parser("worker", help="consumidor da fila de ingestão e agendador dos jobs")
    p = sub.add_parser("job", help="jobs do agendador (DDS §13)")
    jobs = p.add_subparsers(dest="acao", required=True)
    jobs.add_parser("listar", help="último sucesso e atraso de cada job")
    p = jobs.add_parser("executar", help="executa agora um job com execução manual (DD-112)")
    p.add_argument("nome")
    p.add_argument("--minutos", type=float, help="para depois deste tempo e guarda o cursor (rotinas do acervo)")
    p = jobs.add_parser("registrar", help="registra o backup ou a cópia para o pen drive (DD-62)")
    p.add_argument("nome", choices=["backup", "copia_pendrive"])
    p.add_argument("--resultado", required=True, choices=["sucesso", "falha"])
    p.add_argument("--inicio", required=True, help="ISO 8601, como date --iso-8601=seconds")
    p.add_argument("--fim", required=True, help="ISO 8601")
    p.add_argument("--itens", type=int, help="opcional: quantidade de arquivos, por exemplo")
    for nome, ajuda in (("documentos-revarrer", "revarredura antimalware do acervo"),
                        ("documentos-hash", "conferência de hash do acervo")):  # fmt: skip
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("--depois-de", help="cursor devolvido pela execução anterior")
        p.add_argument("--minutos", type=float, help="para depois deste tempo e mostra o cursor")
    sub.add_parser("documentos-orfaos", help="remove do cofre arquivo sem documento")
    p = sub.add_parser("carga", help="carga inicial das planilhas (DDS §14), pelo TI")
    cargas = p.add_subparsers(dest="acao", required=True)
    for nome, ajuda in (("simular", "simulação: desfaz tudo e deixa só o relatório (DD-66)"),
                        ("efetivar", "efetivação única (DD-66, DD-72)")):  # fmt: skip
        p = cargas.add_parser(nome, help=ajuda)
        p.add_argument("pasta", help="pasta com p1_enderecos.xlsx, p4_entradas.xlsx e p3_eventos.xlsx")
        p.add_argument("--login", required=True, help="login do TI; a senha é pedida sem eco")
        if nome == "efetivar":
            p.add_argument("--definitiva", action="store_true", help="confirma que a efetivação não se desfaz")
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
        elif args.comando == "worker":
            return worker()
        elif args.comando == "job":
            if args.acao == "listar":
                return job_listar()
            if args.acao == "executar":
                return job_executar(args.nome, args.minutos)
            return job_registrar(args.nome, args.resultado, args.inicio, args.fim, args.itens)
        elif args.comando == "carga":
            return carga(args.acao, args.pasta, args.login, getattr(args, "definitiva", False))
        elif args.comando in ("documentos-revarrer", "documentos-hash", "documentos-orfaos"):
            return rotina_documentos(args.comando, getattr(args, "depois_de", None), getattr(args, "minutos", None))
        else:
            return verificar_cadeia()
    except ConfiguracaoInvalida as erro:
        print(f"Falhou: {erro}", file=sys.stderr)  # mensagem nossa, sem dado pessoal nem segredo
        return 1
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
