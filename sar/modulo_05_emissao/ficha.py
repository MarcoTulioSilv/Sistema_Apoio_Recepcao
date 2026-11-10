"""A ficha de cadastro em lista (DOC-01, DD-106, DEC-76): só os campos preenchidos, na ordem da ficha de papel
(RF-106), com telefones, contatos e períodos em qualquer quantidade. Função pura sobre a Ficha do MOD-02."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sar.modulo_02_cadastro.contrato import Ficha, Sexo, TipoCobertura, TipoEvento, TipoTelefone
from sar.modulo_05_emissao import regras

SEXOS = {Sexo.FEMININO: "Feminino", Sexo.MASCULINO: "Masculino"}
TELEFONES = {TipoTelefone.CELULAR: "celular", TipoTelefone.FIXO: "fixo", TipoTelefone.RECADO: "recado"}
EVENTOS = {TipoEvento.OBITO: "Óbito", TipoEvento.ALTA: "Alta", TipoEvento.TRANSFERENCIA: "Transferência",
           TipoEvento.TRANSPLANTE: "Transplante", TipoEvento.DESISTENCIA: "Desistência"}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Secao:
    titulo: str
    itens: tuple[tuple[str, str], ...]  # (rótulo, valor), só os preenchidos


def cpf(digitos: str) -> str:
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}" if len(digitos) == 11 else digitos


def cns(digitos: str) -> str:
    return f"{digitos[:3]} {digitos[3:7]} {digitos[7:11]} {digitos[11:]}" if len(digitos) == 15 else digitos


def _telefone(ddd: str, numero: str, tipo: TipoTelefone) -> str:
    return f"{regras.telefone(ddd + numero)} ({TELEFONES[tipo]})"


def _data(valor: date | None) -> str:
    return regras.data_curta(valor)


def _preenchidos(itens: list[tuple[str, str | None]]) -> tuple[tuple[str, str], ...]:
    return tuple((rotulo, valor.strip()) for rotulo, valor in itens if valor and valor.strip())


def secoes(ficha: Ficha) -> list[Secao]:
    d = ficha.dados
    rg = " ".join(p for p in (d.rg, d.rg_orgao) if p) or None
    naturalidade = f"{ficha.naturalidade.nome}-{ficha.naturalidade.uf}" if ficha.naturalidade else None
    residencia = f"{ficha.residencia.nome}-{ficha.residencia.uf}" if ficha.residencia else None
    endereco = ", ".join(p for p in (d.logradouro, d.numero, d.complemento) if p) or None
    resultado = [
        Secao("Identificação", _preenchidos([
            ("Prontuário", d.prontuario), ("Nome", d.nome), ("Data de nascimento", _data(d.data_nascimento)),
            ("Sexo", SEXOS[d.sexo] if d.sexo else None), ("Nome da mãe", d.nome_mae),
            ("CPF", cpf(d.cpf) if d.cpf else None), ("CNS", cns(d.cns) if d.cns else None), ("RG", rg),
            ("Naturalidade", naturalidade),
        ])),
        Secao("Endereço", _preenchidos([
            ("Logradouro", endereco), ("Bairro", d.bairro), ("Município", residencia),
            ("CEP", regras.cep(d.cep) if d.cep else None),
        ])),
        Secao("Telefones do paciente", tuple(
            (f"Telefone {i}", _telefone(t.ddd, t.numero, t.tipo)) for i, t in enumerate(ficha.telefones, 1)
        )),
        Secao("Contatos", tuple(
            (c.parentesco or "Contato", " · ".join([c.nome, *(_telefone(t.ddd, t.numero, t.tipo)
                                                              for t in c.telefones)]))
            for c in ficha.contatos
        )),
    ]  # fmt: skip
    periodos = []
    for numero, periodo in enumerate(ficha.periodos, 1):
        partes = [f"início em {_data(periodo.inicio)}"]
        if periodo.cobertura is not None:
            cobertura = periodo.cobertura
            if cobertura.tipo is TipoCobertura.SUS:
                partes.append("SUS")
            else:
                partes.append(" ".join(p for p in ("Convênio", cobertura.convenio_nome, cobertura.carteirinha) if p))
        if periodo.evento_tipo is not None:
            partes.append(f"{EVENTOS[periodo.evento_tipo]} em {_data(periodo.evento_data)}")
        periodos.append((f"Período {numero}", "; ".join(partes)))
    resultado.append(Secao("Tratamento", tuple(periodos)))
    return [s for s in resultado if s.itens]
