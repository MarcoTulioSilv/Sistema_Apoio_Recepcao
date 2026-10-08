"""Regras puras do MOD-01, sem banco e sem relógio global (DD-12)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import datetime
from functools import cache
from itertools import pairwise
from pathlib import Path

from sar.modulo_01_acesso.contrato import ResultadoVerificacao
from sar.modulo_08_dados.canonico import calcular_hash, json_do_registro
from sar.modulo_08_dados.interfaces.trilha import Ancora, Cabeca, Elo
from sar.nucleo.erros import RegraViolada


def json_do_elo(elo: Elo) -> str:
    return json_do_registro(
        id=elo.id,
        instante=elo.instante,
        usuario_id=elo.usuario_id,
        autorizador_id=elo.autorizador_id,
        operacao=elo.operacao,
        entidade=elo.entidade,
        entidade_id=elo.entidade_id,
        alteracoes=elo.alteracoes,
        motivo=elo.motivo,
        origem=elo.origem,
        sessao_id=elo.sessao_id,
        requisicao_id=elo.requisicao_id,
        versao_formato=elo.versao_formato,
    )


def verificar_elos(
    elos: Iterable[Elo],
    *,
    primeiro_id: int,
    hash_inicial: str,
    cabeca: Cabeca,
    ancoras: Sequence[Ancora],
) -> ResultadoVerificacao:
    """Percorre a cadeia do primeiro elo (ou do ponto de corte) até a cabeça lida no início.

    Aponta o primeiro elo que: falta na sequência; não aponta para o hash do anterior; não confere com o
    próprio hash; ou diverge de uma âncora já registrada (alteração com o hash recalculado). No fim, a cabeça
    precisa ser o último elo — senão, registros do fim foram apagados.
    """
    por_id = {a.ate_registro_id: a for a in ancoras}
    esperado, anterior, verificados = primeiro_id, hash_inicial, 0
    ultimo_instante: dict[int, datetime] = {}

    def divergente(id_: int, motivo: str) -> ResultadoVerificacao:
        cobrindo = [a.registrada_em for a in ancoras if a.ate_registro_id >= id_]
        depois_de = max(cobrindo) if cobrindo else ultimo_instante.get(id_)
        return ResultadoVerificacao(False, verificados, id_, motivo, depois_de)

    for elo in elos:
        ultimo_instante[elo.id] = elo.instante
        if elo.id != esperado:
            return divergente(esperado, "sequencia")
        if elo.hash_anterior != anterior:
            return divergente(elo.id, "elo")
        if calcular_hash(anterior, json_do_elo(elo)) != elo.hash_registro:
            return divergente(elo.id, "hash")
        ancora = por_id.get(elo.id)
        if ancora is not None and ancora.hash != elo.hash_registro:
            return divergente(elo.id, "ancora")
        anterior, esperado, verificados = elo.hash_registro, esperado + 1, verificados + 1
    if esperado - 1 != cabeca.ultimo_id or anterior != cabeca.ultimo_hash:
        return divergente(esperado, "cabeca")
    return ResultadoVerificacao(True, verificados)


def cinco_anos_antes(instante: datetime) -> datetime:
    """Limite da guarda da trilha (DEC-45). 29 de fevereiro vira 28, no ano sem o dia."""
    try:
        return instante.replace(year=instante.year - 5)
    except ValueError:
        return instante.replace(year=instante.year - 5, day=28)


TAMANHO_CODIGO = 16  # 64 bits: forjar uma trilha com o mesmo começo de hash é inviável (DD-86)


def codigo_do_hash(hash_hex: str) -> str:
    """'7f3a91c24d0be58a…' → '7F3A-91C2-4D0B-E58A'."""
    inicio = hash_hex[:TAMANHO_CODIGO].upper()
    return "-".join(inicio[i : i + 4] for i in range(0, TAMANHO_CODIGO, 4))


def normalizar_codigo(texto: str) -> str | None:
    """O código como digitado de um papel (com ou sem traços e espaços), em minúsculas; None se não tiver
    exatamente 16 hexadecimais."""
    limpo = re.sub(r"[\s-]", "", texto).lower()
    return limpo if re.fullmatch(rf"[0-9a-f]{{{TAMANHO_CODIGO}}}", limpo) else None


# ------------------------------------------------------------------ senha (DD-83) e bloqueio (§5.2)
SENHA_MINIMO, SENHA_MAXIMO, SENHA_MAXIMO_BYTES = 8, 64, 72  # 72 bytes: limite do bcrypt
_TECLADO = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890")


@cache
def _senhas_fracas() -> frozenset[str]:
    linhas = (Path(__file__).parent / "senhas_fracas.txt").read_text(encoding="utf-8").splitlines()
    return frozenset(linha.strip() for linha in linhas if linha.strip() and not linha.startswith("#"))


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", "", sem_acento.lower())


def _sequencia(texto: str) -> bool:
    """'12345678', 'hgfedcba', 'qwertyui': caracteres consecutivos, ou um trecho de uma fileira do teclado."""
    passos = {ord(b) - ord(a) for a, b in pairwise(texto)}
    if passos in ({1}, {-1}):
        return True
    return any(texto in fileira or texto in fileira[::-1] for fileira in _TECLADO)


def _repeticao(texto: str) -> bool:
    """'aaaaaaaa', 'abababab', 'abcabcab': o mesmo pedaço de até 3 caracteres repetido."""
    return any(texto == (texto[:n] * len(texto))[: len(texto)] for n in (1, 2, 3))


def validar_senha(senha: str, login: str, nome: str) -> None:
    """Recusa só as muito fracas (DD-83); nenhuma regra de composição. RegraViolada com o motivo."""
    if not SENHA_MINIMO <= len(senha) <= SENHA_MAXIMO or len(senha.encode()) > SENHA_MAXIMO_BYTES:
        raise RegraViolada("senha.tamanho", {"minimo": SENHA_MINIMO, "maximo": SENHA_MAXIMO})
    normalizada = _normalizar(senha)
    base = re.sub(r"[\W\d_]+$", "", normalizada)  # "Brasil2024!" → "brasil"
    if (
        normalizada in _senhas_fracas()
        or base in _senhas_fracas()
        or _sequencia(normalizada)
        or _repeticao(normalizada)
    ):
        raise RegraViolada("senha.fraca")
    partes = [p for p in re.split(r"[^a-z0-9]+", _normalizar(login)) if len(p) >= 3] + [
        p for p in (_normalizar(n) for n in re.split(r"[\s\W]+", nome)) if len(p) >= 4
    ]
    if any(parte in normalizada for parte in partes):
        raise RegraViolada("senha.contem_nome")


def minutos_de_bloqueio(tentativas: int, limite: int, inicial: int, teto: int) -> int | None:
    """Após `limite` falhas seguidas, bloqueio de `inicial` minutos, que dobra a cada nova falha até o teto
    (§5.2). None enquanto não chega ao limite."""
    if tentativas < limite:
        return None
    return min(inicial << min(tentativas - limite, 16), teto)  # dobra a cada falha: inicial × 2^n
