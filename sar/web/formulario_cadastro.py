"""Formulário do cadastro (RF-101, RF-106, RF-201, RF-202): da tela para o contrato do MOD-02 e de volta.

Cada campo tem nome único, também nas linhas repetidas (tel-0-ddd, contato-1-tel-0-numero). O mesmo dicionário
de texto serve ao rascunho (RF-919), que guarda o preenchimento como foi digitado, e à remontagem da tela depois
de um erro. Só apresentação: as regras são do MOD-02, que decide."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from sar.modulo_02_cadastro.contrato import (
    DadosCobertura,
    DadosContato,
    DadosPaciente,
    DadosTelefone,
    Sexo,
    TipoCobertura,
    TipoTelefone,
)
from sar.nucleo.erros import RegraViolada

CAMPOS = (
    "prontuario", "nome", "inicio", "nascimento", "sexo", "mae", "cpf", "cns", "rg", "rg_orgao", "naturalidade_uf",
    "naturalidade", "cep", "logradouro", "numero", "complemento", "bairro", "municipio", "cobertura", "convenio",
    "carteirinha",
)  # fmt: skip
_TELEFONE = re.compile(r"^tel-(\d{1,2})-(ddd|numero|tipo)$")
_CONTATO = re.compile(r"^contato-(\d{1,2})-(nome|parentesco)$")
_TELEFONE_CONTATO = re.compile(r"^contato-(\d{1,2})-tel-(\d{1,2})-(ddd|numero|tipo)$")
TIPOS_TELEFONE = {TipoTelefone.CELULAR.value: "Celular", TipoTelefone.FIXO.value: "Fixo",
                  TipoTelefone.RECADO.value: "Recado"}  # fmt: skip


@dataclass
class LinhaTelefone:
    prefixo: str  # "tel-0" ou "contato-1-tel-0"
    ddd: str = ""
    numero: str = ""
    tipo: str = TipoTelefone.CELULAR.value

    @property
    def vazia(self) -> bool:
        return not (self.ddd.strip() or self.numero.strip())


@dataclass
class BlocoContato:
    prefixo: str  # "contato-0"
    nome: str = ""
    parentesco: str = ""
    telefones: list[LinhaTelefone] = field(default_factory=list)

    @property
    def vazio(self) -> bool:
        return not (self.nome.strip() or self.parentesco.strip()) and all(t.vazia for t in self.telefones)


def valores(formulario: Mapping[str, str]) -> dict[str, str]:
    """Só os campos do cadastro: o resto do pedido (botão, cabeçalhos do htmx) não vai ao rascunho."""
    return {
        nome: str(valor)
        for nome, valor in formulario.items()
        if nome in CAMPOS or _TELEFONE.match(nome) or _CONTATO.match(nome) or _TELEFONE_CONTATO.match(nome)
    }


def telefones_do_paciente(v: Mapping[str, str]) -> list[LinhaTelefone]:
    indices = sorted({int(m.group(1)) for nome in v if (m := _TELEFONE.match(nome))})
    linhas = [_linha(v, f"tel-{i}") for i in indices]
    return linhas or [LinhaTelefone("tel-0")]  # sempre uma linha para preencher


def contatos(v: Mapping[str, str]) -> list[BlocoContato]:
    indices = sorted({int(m.group(1)) for nome in v if (m := _CONTATO.match(nome) or _TELEFONE_CONTATO.match(nome))})
    blocos = []
    for j in indices:
        prefixo = f"contato-{j}"
        telefones = sorted(
            {int(m.group(2)) for nome in v if (m := _TELEFONE_CONTATO.match(nome)) and int(m.group(1)) == j}
        )
        linhas = [_linha(v, f"{prefixo}-tel-{k}") for k in telefones] or [LinhaTelefone(f"{prefixo}-tel-0")]
        blocos.append(BlocoContato(prefixo, v.get(f"{prefixo}-nome", ""), v.get(f"{prefixo}-parentesco", ""), linhas))
    return blocos or [BlocoContato("contato-0", telefones=[LinhaTelefone("contato-0-tel-0")])]


def _linha(v: Mapping[str, str], prefixo: str) -> LinhaTelefone:
    tipo = v.get(f"{prefixo}-tipo", TipoTelefone.CELULAR.value)
    return LinhaTelefone(prefixo, v.get(f"{prefixo}-ddd", ""), v.get(f"{prefixo}-numero", ""),
                         tipo if tipo in TIPOS_TELEFONE else TipoTelefone.CELULAR.value)  # fmt: skip


def _data(texto: str, campo: str) -> date | None:
    texto = texto.strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise RegraViolada(f"{campo}.formato") from None


@dataclass(frozen=True, slots=True)
class Cadastro:
    dados: DadosPaciente
    inicio: date | None
    cobertura: DadosCobertura | None
    telefones: tuple[DadosTelefone, ...]  # só as linhas preenchidas
    contatos: tuple[DadosContato, ...]
    prefixos_telefones: tuple[str, ...]  # nome da linha no formulário, na mesma ordem: para mostrar o erro nela
    prefixos_contatos: tuple[tuple[str, tuple[str, ...]], ...]

    def campo_do_erro(self, detalhe: Mapping[str, object]) -> str | None:
        """O prefixo da linha do formulário a que o erro do MOD-02 se refere ({"telefone": i}, {"contato": j})."""
        j, i = detalhe.get("contato"), detalhe.get("telefone")
        if isinstance(j, int) and j < len(self.prefixos_contatos):
            prefixo, telefones = self.prefixos_contatos[j]
            return telefones[i] if isinstance(i, int) and i < len(telefones) else prefixo
        if isinstance(i, int) and i < len(self.prefixos_telefones):
            return self.prefixos_telefones[i]
        return None


def _telefone(linha: LinhaTelefone) -> DadosTelefone:
    return DadosTelefone(linha.ddd, linha.numero, TipoTelefone(linha.tipo))


def ler(v: Mapping[str, str]) -> Cadastro:
    """RegraViolada com o campo do formulário no código ("inicio.formato", "convenio.formato")."""
    sexo = v.get("sexo", "")
    convenio = v.get("convenio", "").strip()
    if convenio and not convenio.isdigit():
        raise RegraViolada("convenio.formato")
    cobertura = None
    if v.get("cobertura") in (TipoCobertura.SUS.value, TipoCobertura.CONVENIO.value):
        tipo = TipoCobertura(v["cobertura"])
        cobertura = DadosCobertura(
            tipo, int(convenio) if convenio and tipo is TipoCobertura.CONVENIO else None,
            v.get("carteirinha") if tipo is TipoCobertura.CONVENIO else None,
        )  # fmt: skip
    dados = DadosPaciente(
        prontuario=v.get("prontuario"),
        nome=v.get("nome"),
        data_nascimento=_data(v.get("nascimento", ""), "data_nascimento"),
        sexo=Sexo(sexo) if sexo in (Sexo.FEMININO.value, Sexo.MASCULINO.value) else None,
        nome_mae=v.get("mae"),
        cpf=v.get("cpf"),
        cns=v.get("cns"),
        rg=v.get("rg"),
        rg_orgao=v.get("rg_orgao"),
        naturalidade_municipio=v.get("naturalidade") or None,
        logradouro=v.get("logradouro"),
        numero=v.get("numero"),
        complemento=v.get("complemento"),
        bairro=v.get("bairro"),
        municipio=v.get("municipio") or None,
        cep=v.get("cep"),
    )
    telefones = [t for t in telefones_do_paciente(v) if not t.vazia]
    blocos = [b for b in contatos(v) if not b.vazio]
    preenchidos = [[t for t in b.telefones if not t.vazia] for b in blocos]
    return Cadastro(
        dados=dados,
        inicio=_data(v.get("inicio", ""), "inicio"),
        cobertura=cobertura,
        telefones=tuple(_telefone(t) for t in telefones),
        contatos=tuple(
            DadosContato(b.nome, b.parentesco or None, tuple(_telefone(t) for t in linhas))
            for b, linhas in zip(blocos, preenchidos, strict=True)
        ),
        prefixos_telefones=tuple(t.prefixo for t in telefones),
        prefixos_contatos=tuple(
            (b.prefixo, tuple(t.prefixo for t in linhas)) for b, linhas in zip(blocos, preenchidos, strict=True)
        ),
    )
