"""Pendências (DDS §11, RF-1010, RNF-408): a tela única de cada perfil e a contagem da tela inicial.

O que cada perfil vê decide o MOD-07, pela matriz (DD-55); aqui só se agrupa por prioridade e se escolhe o botão.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from flask import Blueprint, current_app, render_template

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_07_pendencias.contrato import ItemPendencia, Prioridade, Resumo
from sar.nucleo.contexto import Contexto
from sar.web import contexto_atual
from sar.web.configuracao import ServicosWeb
from sar.web.rotulos import ACOES_PENDENCIA, PENDENCIAS_CURTAS, PRIORIDADES

bp = Blueprint("pendencias", __name__, url_prefix="/pendencias")
GUARDA = PermissionGuard()
POR_TIPO = 5  # acima disso, num tipo e numa prioridade, o resto fica em "Mais N de ..." (aprovado na maquete)
SEM_TELA = "/pendencias"  # a fonte não tem tela de resolução para este perfil
SEM_ETIQUETA_NO_CARTAO = frozenset({"extra_alem_do_limite"})
JA_NA_FICHA = frozenset({"cadastro_incompleto", "possivel_duplicidade", "evento_sem_comprovante"})


@dataclass(frozen=True, slots=True)
class Linha:
    codigo: str
    titulo: str
    detalhe: str
    destino: str | None
    acao: str


@dataclass
class Grupo:
    prioridade: Prioridade
    nome: str
    classe: str
    etiqueta: str
    linhas: list[Linha] = field(default_factory=list)
    mais: dict[str, list[Linha]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.linhas) + sum(len(v) for v in self.mais.values())


def _servicos() -> ServicosWeb:
    servicos: ServicosWeb = current_app.config["SAR_SERVICOS"]
    return servicos


def destino_permitido(contexto: Contexto, destino: str) -> str | None:
    """Sem botão quando não há tela, ou quando a tela é a ficha e o perfil não a abre (a enfermagem, DEC-55)."""
    if destino == SEM_TELA:
        return None
    if destino.startswith("/pacientes/") and not GUARDA.pode(contexto, "cadastro.paciente.ver_ficha"):
        return None
    return destino


def linha(contexto: Contexto, item: ItemPendencia, nomes: dict[int, str]) -> Linha:
    curta = PENDENCIAS_CURTAS.get(item.codigo, item.codigo)
    nome = nomes.get(item.paciente_id) if item.paciente_id is not None else None
    return Linha(item.codigo, f"{curta}: {nome}" if nome else curta, item.descricao,
                 destino_permitido(contexto, item.destino), ACOES_PENDENCIA.get(item.codigo, "Abrir"))  # fmt: skip


def agrupar(contexto: Contexto, itens: Sequence[ItemPendencia], nomes: dict[int, str]) -> list[Grupo]:
    """Uma seção por prioridade com itens, na ordem que o serviço entregou (a mais antiga primeiro)."""
    grupos = {p: Grupo(p, *PRIORIDADES[p.value]) for p in (Prioridade.URGENCIA, Prioridade.ALTA, Prioridade.NORMAL)}
    vistos: Counter[tuple[Prioridade, str]] = Counter()
    for item in itens:
        grupo, chave = grupos[item.prioridade], (item.prioridade, item.codigo)
        vistos[chave] += 1
        destino = grupo.linhas if vistos[chave] <= POR_TIPO else grupo.mais.setdefault(item.codigo, [])
        destino.append(linha(contexto, item, nomes))
    return [g for g in grupos.values() if g.total]


def etiquetas_dos_pacientes(contexto: Contexto, ids: Sequence[int]) -> dict[int, list[tuple[str, str]]]:
    """Para os cartões do turno (DD-30, RF-922): uma etiqueta por tipo de pendência de cada paciente, na cor da
    prioridade. As extras além do limite ficam de fora, porque o cartão já mostra as extras do mês."""
    if not ids or not GUARDA.pode(contexto, "pendencia.ver"):
        return {}
    saida: dict[int, list[tuple[str, str]]] = {}
    for paciente_id, itens in _servicos().pendencias.dos_pacientes(contexto, ids).items():
        vistos: dict[str, str] = {}
        for item in itens:
            if item.codigo not in vistos and item.codigo not in SEM_ETIQUETA_NO_CARTAO:
                vistos[item.codigo] = PRIORIDADES[item.prioridade.value][2]
        saida[paciente_id] = [(PENDENCIAS_CURTAS.get(c, c), classe) for c, classe in vistos.items()]
    return saida


def outras_da_ficha(contexto: Contexto, paciente_id: int) -> list[tuple[str, str, str, str | None, str]]:
    """As pendências do paciente que a ficha ainda não mostra noutro bloco: (etiqueta, prioridade, descrição, destino,
    ação). O cadastro incompleto, a possível duplicidade e o evento sem comprovante já têm o seu lugar na ficha."""
    if not GUARDA.pode(contexto, "pendencia.ver"):
        return []
    itens = _servicos().pendencias.dos_pacientes(contexto, [paciente_id]).get(paciente_id, [])
    ficha = f"/pacientes/{paciente_id}"
    saida = []
    for item in itens:
        if item.codigo in JA_NA_FICHA:
            continue
        nome, _, etiqueta = PRIORIDADES[item.prioridade.value]
        destino = destino_permitido(contexto, item.destino)
        saida.append((etiqueta, nome, item.descricao, None if destino == ficha else destino,
                      ACOES_PENDENCIA.get(item.codigo, "Abrir")))  # fmt: skip
    return saida


def contagens_da_tela(contexto: Contexto) -> dict[str, int] | None:
    """A contagem do bloco da tela inicial, por prioridade (U, A, N); None para quem não vê pendências."""
    if not GUARDA.pode(contexto, "pendencia.ver"):
        return None
    resumo: Resumo = _servicos().pendencias.resumo(contexto)
    return {prioridade.value: quantidade for prioridade, quantidade in resumo.totais.items()}


@bp.get("")
def lista() -> str:
    contexto = contexto_atual()
    servico = _servicos().pendencias
    itens = servico.listar(contexto)
    grupos = agrupar(contexto, itens, servico.nomes(contexto, itens))
    return render_template("pendencias.html", grupos=grupos, total=len(itens), curtas=PENDENCIAS_CURTAS)


@bp.get("/resumo")
def resumo() -> str:
    """O bloco da tela inicial, a cada minuto, com a marca de requisição automática (DD-57)."""
    return render_template("_pendencias_resumo.html", contagens=contagens_da_tela(contexto_atual()))
