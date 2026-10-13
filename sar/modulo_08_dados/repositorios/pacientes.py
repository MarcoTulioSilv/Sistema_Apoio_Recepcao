"""Repositório do agregado do paciente (SQL)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.pacientes import (
    CamposPaciente,
    CoberturaGravada,
    ColunaUnica,
    ContatoGravado,
    PacienteGravado,
    PeriodoGravado,
    TelefoneGravado,
)
from sar.modulo_08_dados.modelos.cadastro import (
    Cobertura,
    Contato,
    DuplicidadeDescartada,
    Paciente,
    PeriodoTratamento,
    Telefone,
)

# Campo do agregado → coluna da tabela, onde os nomes diferem.
_COLUNAS = {"naturalidade_municipio": "naturalidade_municipio_id", "municipio": "municipio_id"}
_CAMPOS = tuple(CamposPaciente.__dataclass_fields__)


def _escapar_like(termo: str) -> str:
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _valores(campos: CamposPaciente) -> dict[str, Any]:
    return {_COLUNAS.get(nome, nome): getattr(campos, nome) for nome in _CAMPOS}


def _paciente(p: Paciente) -> PacienteGravado:
    campos = CamposPaciente(**{nome: getattr(p, _COLUNAS.get(nome, nome)) for nome in _CAMPOS})
    anulado = p.anulado_em.replace(tzinfo=UTC) if p.anulado_em is not None else None
    return PacienteGravado(p.id, p.versao, campos, p.cep_verificado, anulado)


def _periodo(p: PeriodoTratamento) -> PeriodoGravado:
    return PeriodoGravado(p.id, p.paciente_id, p.inicio, p.evento_tipo, p.evento_data, p.evento_local,
                          p.evento_documento_id)  # fmt: skip


class RepositorioPacienteSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    # ---------------------------------------------------------------- paciente
    def criar(self, campos: CamposPaciente, cep_verificado: bool, em: datetime) -> int:
        linha = Paciente(
            **_valores(campos), cep_verificado=cep_verificado, criado_em=em.astimezone(UTC).replace(tzinfo=None)
        )
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def por_id(self, id: int, travar: bool = False) -> PacienteGravado | None:
        consulta = select(Paciente).where(Paciente.id == id)
        if travar:
            consulta = consulta.with_for_update()
        linha = self._s.scalars(consulta).one_or_none()
        return _paciente(linha) if linha is not None else None

    def atualizar(self, id: int, versao: int, campos: CamposPaciente, cep_verificado: bool) -> bool:
        resultado = self._s.execute(
            update(Paciente)
            .where(Paciente.id == id, Paciente.versao == versao)
            .values(**_valores(campos), cep_verificado=cep_verificado, versao=Paciente.versao + 1),
            execution_options={"synchronize_session": False},
        )
        return bool(getattr(resultado, "rowcount", 0) == 1)

    def quem_usa(self, coluna: ColunaUnica, valor: str) -> int | None:
        return self._s.scalar(select(Paciente.id).where(getattr(Paciente, coluna) == valor))

    def por_nascimento(self, data: date) -> list[PacienteGravado]:
        consulta = select(Paciente).where(Paciente.data_nascimento == data, Paciente.anulado_em.is_(None))
        return [_paciente(p) for p in self._s.scalars(consulta.order_by(Paciente.id))]

    def buscar(self, nome: str | None, exato: str | None, limite: int) -> list[PacienteGravado]:
        condicoes: list[ColumnElement[bool]] = []
        if nome is not None:
            condicoes.append(Paciente.nome.like(f"%{_escapar_like(nome)}%", escape="\\"))
        if exato is not None:
            condicoes += [Paciente.prontuario == exato, Paciente.cpf == exato, Paciente.cns == exato]
        if not condicoes:
            return []
        consulta = select(Paciente).where(or_(*condicoes), Paciente.anulado_em.is_(None))
        return [_paciente(p) for p in self._s.scalars(consulta.order_by(Paciente.nome, Paciente.id).limit(limite))]

    def duplicidade_descartada(self, a: int, b: int) -> bool:
        menor, maior = sorted((a, b))
        consulta = select(DuplicidadeDescartada.id).where(
            DuplicidadeDescartada.paciente_a_id == menor, DuplicidadeDescartada.paciente_b_id == maior
        )
        return self._s.scalar(consulta) is not None

    def descartar_duplicidade(self, a: int, b: int, por: int, em: datetime) -> None:
        menor, maior = sorted((a, b))
        instante = em.astimezone(UTC).replace(tzinfo=None)
        self._s.add(DuplicidadeDescartada(paciente_a_id=menor, paciente_b_id=maior, decidido_por=por,
                                          decidido_em=instante))  # fmt: skip
        self._s.flush()

    # ---------------------------------------------------------------- períodos e coberturas
    def periodos(self, paciente_id: int) -> list[PeriodoGravado]:
        consulta = select(PeriodoTratamento).where(PeriodoTratamento.paciente_id == paciente_id)
        return [_periodo(p) for p in self._s.scalars(consulta.order_by(PeriodoTratamento.inicio))]

    def abrir_periodo(self, paciente_id: int, inicio: date) -> int:
        linha = PeriodoTratamento(paciente_id=paciente_id, inicio=inicio)
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def coberturas(self, periodo_ids: list[int]) -> list[CoberturaGravada]:
        if not periodo_ids:
            return []
        consulta = (
            select(Cobertura)
            .where(Cobertura.periodo_id.in_(periodo_ids))
            .order_by(Cobertura.periodo_id, Cobertura.vigencia_inicio)
        )
        return [
            CoberturaGravada(c.id, c.periodo_id, c.vigencia_inicio, c.tipo, c.convenio_id, c.carteirinha)
            for c in self._s.scalars(consulta)
        ]

    def pacientes_com_periodo_em(self, data: date) -> list[int]:
        consulta = (
            select(PeriodoTratamento.paciente_id)
            .distinct()
            .join(Paciente, Paciente.id == PeriodoTratamento.paciente_id)
            .where(
                PeriodoTratamento.inicio <= data,
                or_(PeriodoTratamento.evento_data.is_(None), PeriodoTratamento.evento_data >= data),
                Paciente.anulado_em.is_(None),
            )
            .order_by(PeriodoTratamento.paciente_id)
        )
        return list(self._s.scalars(consulta))

    # ---------------------------------------------------------------- contatos e telefones
    def contatos(self, paciente_id: int) -> list[ContatoGravado]:
        consulta = select(Contato).where(Contato.paciente_id == paciente_id).order_by(Contato.id)
        return [ContatoGravado(c.id, c.nome, c.parentesco) for c in self._s.scalars(consulta)]

    def telefones(self, paciente_id: int) -> list[TelefoneGravado]:
        dos_contatos = select(Contato.id).where(Contato.paciente_id == paciente_id)
        consulta = (
            select(Telefone)
            .where(or_(Telefone.paciente_id == paciente_id, Telefone.contato_id.in_(dos_contatos)))
            .order_by(Telefone.id)
        )
        return [
            TelefoneGravado(t.id, t.paciente_id, t.contato_id, t.ddd, t.numero, t.tipo)
            for t in self._s.scalars(consulta)
        ]
