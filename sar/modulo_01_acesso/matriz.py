"""Catálogo de operações e matriz de permissões (DDS §4, AD-20): a fonte única de quem pode o quê.

Cada linha espelha uma linha do DDS §4, com a mesma notação: códigos abreviados ("acesso.sessao.entrar /
sair"), condição depois do travessão ("config.parametro.alterar — operacionais") e células "✓", "✓ nota",
"Aut." ou "—". Um teste lê as tabelas do DDS e compara com este catálogo: divergência é falha (como a DD-55
faz com as pendências).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from sar.nucleo.contexto import Perfil


class Acesso(str, Enum):
    EXECUTA = "executa"
    SOLICITA = "solicita"  # "Aut.": só por solicitação aprovada pela administração (DEC-42)


@dataclass(frozen=True, slots=True)
class Celula:
    acesso: Acesso
    nota: str | None = None  # restrição de recurso: "próprio", "pseudonimizado", "simples", "diagnóstico"


@dataclass(frozen=True, slots=True)
class Entrada:
    codigo: str
    condicao: str | None  # variante da mesma operação ("operacionais"/"técnicos", "mês aberto"/"mês fechado")
    celulas: dict[Perfil, Celula]
    auditada: bool


COLUNAS = (Perfil.RECEPCAO, Perfil.ADMINISTRACAO, Perfil.VISUALIZADOR, Perfil.TI, Perfil.ENFERMAGEM, Perfil.SISTEMA)


def celula(texto: str) -> Celula | None:
    """'—' → nenhum acesso; '✓' ou '✓ nota' → executa; 'Aut.' → só solicita."""
    texto = texto.strip()
    if texto in ("—", ""):
        return None
    if texto == "Aut.":
        return Celula(Acesso.SOLICITA)
    if texto.startswith("✓"):
        return Celula(Acesso.EXECUTA, texto[1:].strip() or None)
    raise ValueError(f"célula da matriz não reconhecida: {texto!r}")


def expandir_codigos(texto: str) -> tuple[list[str], str | None]:
    """'`a.b.c` / `d` / `x.e` — condição (nota)' → (['a.b.c', 'a.b.d', 'a.x.e'], 'condição').

    Cada abreviação substitui os últimos segmentos do primeiro código; com tantos segmentos quanto ele, é um
    código completo. Parênteses no fim são comentário, não condição.
    """
    codigos_texto, _, condicao = texto.partition("—")
    tokens = re.findall(r"`([^`]+)`", codigos_texto)
    if not tokens:
        raise ValueError(f"linha sem código de operação: {texto!r}")
    base = tokens[0].split(".")
    codigos = [tokens[0]]
    for token in tokens[1:]:
        partes = token.split(".")
        codigos.append(token if len(partes) >= len(base) else ".".join(base[: -len(partes)] + partes))
    condicao = re.sub(r"\s*\([^)]*\)\s*$", "", condicao).strip()
    return codigos, condicao or None


def linha(operacao: str, r: str, a: str, v: str, t: str, e: str, s: str, auditada: bool) -> list[Entrada]:
    """Uma linha da tabela do DDS §4 → uma entrada por código (o teste de conformidade usa a mesma função)."""
    codigos, condicao = expandir_codigos(operacao)
    celulas = {perfil: c for perfil, texto in zip(COLUNAS, (r, a, v, t, e, s), strict=True) if (c := celula(texto))}
    return [Entrada(codigo, condicao, celulas, auditada) for codigo in codigos]


S, N = True, False  # auditada: Sim / Não

# fmt: off
_CATALOGO = [
    # ---- §4.1 MOD-01 Acesso e auditoria             R       A          V    T                   E    S
    linha("`acesso.sessao.entrar` / `sair`",           "✓",    "✓",       "✓", "✓",                "✓", "—", S),
    linha("`acesso.senha.trocar_propria`",             "✓",    "✓",       "✓", "✓",                "✓", "—", S),
    linha("`acesso.usuario.consultar`",                "—",    "—",       "—", "✓",                "—", "—", N),
    linha("`acesso.usuario.criar` / `alterar_perfil` / `inativar` / `reativar`",
                                                        "—",    "—",       "—", "✓",                "—", "—", S),
    linha("`acesso.usuario.redefinir_senha`",          "—",    "—",       "—", "✓",                "—", "—", S),
    linha("`acesso.usuario.registrar_termo_ciencia`",  "—",    "—",       "—", "✓",                "—", "—", S),
    linha("`acesso.auditoria.consultar`",              "—",    "✓",       "—", "✓ pseudonimizado", "—", "—", S),
    linha("`acesso.cadeia.verificar`",                 "—",    "—",       "—", "✓",                "—", "✓", S),
    linha("`acesso.trilha.expurgar`",                  "—",    "—",       "—", "—",                "—", "✓", N),
    linha("`acesso.aviso_integridade.ver`",            "—",    "✓ simples", "—", "✓ diagnóstico",  "—", "—", S),
    linha("`acesso.aviso_integridade.encerrar`",       "—",    "✓",       "—", "—",                "—", "—", S),
    linha("`acesso.ancora.conferir`",                  "—",    "✓",       "—", "✓",                "—", "—", S),
    linha("`acesso.autorizacao.solicitar`",            "✓",    "✓",       "—", "—",                "✓", "—", S),
    linha("`acesso.autorizacao.decidir`",              "—",    "✓",       "—", "—",                "—", "—", S),
    linha("`acesso.autorizacao.cancelar_propria`",     "✓",    "✓",       "—", "—",                "✓", "—", S),
    # ---- §4.2 MOD-02 Cadastro
    linha("`cadastro.paciente.buscar`",                "✓",    "✓",       "✓", "—", "✓", "—", S),
    linha("`cadastro.paciente.ver_identificacao`",     "✓",    "✓",       "✓", "—", "✓", "—", S),
    linha("`cadastro.paciente.ver_ficha`",             "✓",    "✓",       "✓", "—", "—", "—", S),
    linha("`cadastro.paciente.criar`",                 "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.paciente.atualizar`",             "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.paciente.descartar_duplicidade`", "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.paciente.anular`",                "Aut.", "Aut.",    "—", "—", "—", "—", S),
    linha("`cadastro.contato.gerir` / `cadastro.telefone.gerir`",
                                                        "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.periodo.abrir`",                  "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.cobertura.registrar`",            "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.evento.registrar`",               "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`cadastro.evento.corrigir` / `remover`",    "Aut.", "Aut.",    "—", "—", "—", "—", S),
    linha("`cadastro.rascunho.salvar` / `retomar` / `descartar`",
                                                        "✓ próprio", "✓ próprio", "—", "—", "—", "—", S),
    linha("`cadastro.rascunho.descartar_expirados`",   "—",    "—",       "—", "—", "—", "✓", S),
    linha("`cadastro.cep.consultar`",                  "✓",    "✓",       "—", "—", "—", "—", N),
    # ---- §4.3 MOD-03 Operação
    linha("`operacao.escala.consultar`",               "✓",    "✓",       "✓", "—", "✓",    "—", N),
    linha("`operacao.alocacao.registrar` / `registrar_em_lote`",
                                                        "—",    "—",       "—", "—", "✓",    "—", S),
    linha("`operacao.alocacao.registrar_retroativa`",  "—",    "—",       "—", "—", "Aut.", "—", S),
    linha("`operacao.troca.registrar` / `cancelar`",   "—",    "—",       "—", "—", "✓",    "—", S),
    linha("`operacao.troca.cancelar_realizada`",       "—",    "—",       "—", "—", "Aut.", "—", S),
    linha("`operacao.extra.registrar` / `cancelar`",   "—",    "—",       "—", "—", "✓",    "—", S),
    linha("`operacao.sessao.ver`",                     "✓",    "✓",       "✓", "—", "✓",    "—", N),
    linha("`operacao.sessao.preparar` — próximo turno com pendências",
                                                        "✓",    "✓",       "—", "—", "✓",    "—", N),
    linha("`operacao.frequencia.marcar_ausencia` / `acrescentar_paciente`",
                                                        "✓",    "✓",       "—", "—", "—",    "—", S),
    linha("`operacao.sessao.confirmar`",               "✓",    "✓",       "—", "—", "—",    "—", S),
    linha("`operacao.sessao.registrar_nao_realizada`", "—",    "✓",       "—", "—", "—",    "—", S),
    linha("`operacao.sessao.reabrir`",                 "Aut.", "Aut.",    "—", "—", "—",    "—", S),
    linha("`operacao.presenca.alterar_confirmada`",    "Aut.", "Aut.",    "—", "—", "—",    "—", S),
    linha("`operacao.pareamento.refazer` — mês aberto", "✓",   "✓",       "—", "—", "—",    "—", S),
    linha("`operacao.pareamento.refazer` — mês fechado", "Aut.", "Aut.",  "—", "—", "—",    "—", S),
    linha("`operacao.presenca.dar_ciencia`",           "—",    "—",       "—", "—", "✓",    "—", S),
    linha("`operacao.balanco.consultar`",              "✓",    "✓",       "✓", "—", "✓",    "—", S),
    # ---- §4.4 MOD-04 Documentos
    linha("`documento.ingestao.abrir` / `conferir` / `incorporar` / `rejeitar`",
                                                        "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`documento.nova_versao`",                   "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`documento.listar`",                        "✓",    "✓",       "✓", "—", "—", "—", S),
    linha("`documento.ver`",                           "✓",    "✓",       "✓", "—", "—", "—", S),
    linha("`documento.baixar`",                        "—",    "✓",       "—", "—", "—", "—", S),
    linha("`documento.revincular`",                    "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`documento.descartar_fim_retencao`",        "—",    "Aut.",    "—", "—", "—", "—", S),
    linha("`documento.desbloquear`",                   "—",    "Aut.",    "—", "—", "—", "—", S),
    linha("`documento.integridade.verificar` / `rescan`", "—", "—",       "—", "✓", "—", "✓", S),
    linha("`documento.ingestao.processar` / `expirar` / `varrer_orfaos`",
                                                        "—",    "—",       "—", "—", "—", "✓", S),
    # ---- §4.5 MOD-05 Emissão e relatórios
    linha("`emissao.documento.emitir`",                "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`emissao.cracha.emitir`",                   "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`emissao.modelo.enviar` / `ativar` / `reverter`",
                                                        "—",    "✓",       "—", "—", "—", "—", S),
    linha("`relatorio.operacional.ver`",               "✓",    "✓",       "✓", "—", "✓", "—", S),
    linha("`relatorio.gerencial.ver`",                 "—",    "✓",       "✓", "—", "—", "—", S),
    linha("`relatorio.aniversariantes.ver`",           "✓",    "✓",       "—", "—", "—", "—", N),
    linha("`relatorio.exportar`",                      "—",    "✓",       "—", "—", "—", "—", S),
    # ---- §4.6 MOD-06 Configuração
    linha("`config.parametro.alterar` — operacionais", "—",    "✓",       "—", "—", "—", "—", S),
    linha("`config.parametro.alterar` — técnicos",     "—",    "—",       "—", "✓", "—", "—", S),
    linha("`config.institucional.alterar` / `logotipo.enviar`",
                                                        "—",    "✓",       "—", "—", "—", "—", S),
    linha("`config.convenio.gerir`",                   "—",    "✓",       "—", "—", "—", "—", S),
    linha("`config.consultar`",                        "✓",    "✓",       "✓", "✓", "✓", "✓", N),
    linha("`config.municipio.incluir`",                "—",    "—",       "—", "✓", "—", "—", S),
    # ---- §4.7 MOD-07 Pendências
    linha("`pendencia.ver` — cada perfil vê só as linhas dele",
                                                        "✓",    "✓",       "✓", "✓", "✓", "—", N),
    # ---- §4.8 MOD-08 Dados e MOD-09 Agendamento
    linha("`agendamento.execucoes.ver`",               "—",    "—",       "—", "✓", "—", "—", N),
    linha("`agendamento.job.executar_agora` — só jobs marcados como seguros na §13.1",
                                                        "—",    "—",       "—", "✓", "—", "—", S),
    linha("`agendamento.backup.registrar`",            "—",    "—",       "—", "—", "—", "✓", S),
    # ---- §4.9 MOD-10 Carga inicial
    linha("`carga.simular` / `carga.efetivar`",        "—",    "—",       "—", "✓", "—", "—", S),
    linha("`carga.excecoes.ver`",                      "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`carga.conferencia.registrar`",             "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`carga.aceitar`",                           "—",    "✓",       "—", "—", "—", "—", S),
    # ---- §4.10 MOD-11 Atendimento ao titular
    linha("`titular.requisicao.registrar`",            "✓",    "✓",       "—", "—", "—", "—", S),
    linha("`titular.requisicao.consultar`",            "✓",    "✓",       "✓", "—", "—", "—", S),
    linha("`titular.requisicao.atender` / `negar`",    "—",    "✓",       "—", "—", "—", "—", S),
    linha("`titular.copia.gerar`",                     "—",    "✓",       "—", "—", "—", "—", S),
]
# fmt: on

MATRIZ: tuple[Entrada, ...] = tuple(entrada for linha in _CATALOGO for entrada in linha)
