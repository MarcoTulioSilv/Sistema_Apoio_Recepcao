"""Repositório do agregado do paciente (SQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, or_, select, update
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
    return PacienteGravado(p.id, p.versao, campos, p.cep_verificado, anulado, p.criado_em.replace(tzinfo=UTC))


def _periodo(p: PeriodoTratamento) -> PeriodoGravado:
    registrado = p.evento_registrado_em.replace(tzinfo=UTC) if p.evento_registrado_em is not None else None
    return PeriodoGravado(p.id, p.paciente_id, p.inicio, p.evento_tipo, p.evento_data, p.evento_local,
                          p.evento_documento_id, registrado)  # fmt: skip


def _contato(c: Contato) -> ContatoGravado:
    return ContatoGravado(c.id, c.paciente_id, c.nome, c.parentesco)


def _telefone(t: Telefone) -> TelefoneGravado:
    return TelefoneGravado(t.id, t.paciente_id, t.contato_id, t.ddd, t.numero, t.tipo)


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

    def anular(self, id: int, em: datetime) -> None:
        dos_contatos = select(Contato.id).where(Contato.paciente_id == id)
        self._s.execute(delete(Telefone).where(or_(Telefone.paciente_id == id, Telefone.contato_id.in_(dos_contatos))))
        self._s.execute(delete(Contato).where(Contato.paciente_id == id))
        apagados = {_COLUNAS.get(nome, nome): None for nome in _CAMPOS}
        self._s.execute(
            update(Paciente)
            .where(Paciente.id == id)
            .values(**apagados, cep_verificado=False, anulado_em=em.astimezone(UTC).replace(tzinfo=None),
                    versao=Paciente.versao + 1),
            execution_options={"synchronize_session": False},
        )  # fmt: skip

    def definir_cep_verificado(self, id: int, verificado: bool) -> None:
        self._s.execute(
            update(Paciente).where(Paciente.id == id).values(cep_verificado=verificado),
            execution_options={"synchronize_session": False},
        )

    def quem_usa(self, coluna: ColunaUnica, valor: str) -> int | None:
        return self._s.scalar(select(Paciente.id).where(getattr(Paciente, coluna) == valor))

    def por_nascimento(self, data: date) -> list[PacienteGravado]:
        consulta = select(Paciente).where(Paciente.data_nascimento == data, Paciente.anulado_em.is_(None))
        return [_paciente(p) for p in self._s.scalars(consulta.order_by(Paciente.id))]

    def buscar(
        self, nome: str | None, prontuario: str | None, numero: str | None, limite: int, deslocamento: int = 0
    ) -> list[PacienteGravado]:
        condicoes: list[ColumnElement[bool]] = []
        if nome is not None:
            condicoes.append(Paciente.nome.like(f"%{_escapar_like(nome)}%", escape="\\"))
        if prontuario is not None:
            condicoes.append(Paciente.prontuario.like(f"{_escapar_like(prontuario)}%", escape="\\"))
        if numero is not None:  # só dígitos ASCII: o termo com acento nem chega às colunas ASCII de CPF e CNS
            condicoes += [Paciente.cpf.like(f"{numero}%"), Paciente.cns.like(f"{numero}%")]
        consulta = select(Paciente).where(Paciente.anulado_em.is_(None))
        if condicoes:
            consulta = consulta.where(or_(*condicoes))
        consulta = consulta.order_by(Paciente.nome, Paciente.id).offset(deslocamento).limit(limite)
        return [_paciente(p) for p in self._s.scalars(consulta)]

    def vivos(self, ids: Sequence[int] | None) -> list[PacienteGravado]:
        consulta = select(Paciente).where(Paciente.anulado_em.is_(None))
        if ids is not None:
            consulta = consulta.where(Paciente.id.in_(list(ids)))
        return [_paciente(p) for p in self._s.scalars(consulta.order_by(Paciente.id))]

    def periodos_de(self, ids: Sequence[int] | None) -> list[PeriodoGravado]:
        consulta = (
            select(PeriodoTratamento)
            .join(Paciente, Paciente.id == PeriodoTratamento.paciente_id)
            .where(Paciente.anulado_em.is_(None))
        )
        if ids is not None:
            consulta = consulta.where(PeriodoTratamento.paciente_id.in_(list(ids)))
        ordem = (PeriodoTratamento.paciente_id, PeriodoTratamento.inicio)
        return [_periodo(p) for p in self._s.scalars(consulta.order_by(*ordem))]

    def descartes(self) -> set[tuple[int, int]]:
        pares = self._s.execute(select(DuplicidadeDescartada.paciente_a_id, DuplicidadeDescartada.paciente_b_id))
        return {(a, b) for a, b in pares}

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

    def periodo(self, id: int) -> PeriodoGravado | None:
        linha = self._s.get(PeriodoTratamento, id)
        return _periodo(linha) if linha is not None else None

    def gravar_evento(
        self,
        periodo_id: int,
        tipo: str | None,
        data: date | None,
        local: str | None,
        documento_id: bytes | None,
        registrado_em: datetime | None,
    ) -> None:
        linha = self._s.get_one(PeriodoTratamento, periodo_id)
        linha.evento_tipo, linha.evento_data, linha.evento_local = tipo, data, local
        linha.evento_documento_id = documento_id
        linha.evento_registrado_em = registrado_em.astimezone(UTC).replace(tzinfo=None) if registrado_em else None
        self._s.flush()

    def criar_cobertura(
        self, periodo_id: int, inicio: date, tipo: str, convenio_id: int | None, carteirinha: str | None
    ) -> int:
        linha = Cobertura(
            periodo_id=periodo_id, vigencia_inicio=inicio, tipo=tipo, convenio_id=convenio_id, carteirinha=carteirinha
        )
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
        return [_contato(c) for c in self._s.scalars(consulta)]

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

    def contato(self, id: int) -> ContatoGravado | None:
        linha = self._s.get(Contato, id)
        return _contato(linha) if linha is not None else None

    def criar_contato(self, paciente_id: int, nome: str, parentesco: str | None) -> int:
        linha = Contato(paciente_id=paciente_id, nome=nome, parentesco=parentesco)
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def alterar_contato(self, id: int, nome: str, parentesco: str | None) -> None:
        linha = self._s.get_one(Contato, id)
        linha.nome, linha.parentesco = nome, parentesco
        self._s.flush()

    def remover_contato(self, id: int) -> None:
        self._s.execute(delete(Telefone).where(Telefone.contato_id == id))
        self._s.execute(delete(Contato).where(Contato.id == id))

    def telefone(self, id: int) -> TelefoneGravado | None:
        linha = self._s.get(Telefone, id)
        return _telefone(linha) if linha is not None else None

    def criar_telefone(self, paciente_id: int | None, contato_id: int | None, ddd: str, numero: str, tipo: str) -> int:
        linha = Telefone(paciente_id=paciente_id, contato_id=contato_id, ddd=ddd, numero=numero, tipo=tipo)
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def alterar_telefone(self, id: int, ddd: str, numero: str, tipo: str) -> None:
        linha = self._s.get_one(Telefone, id)
        linha.ddd, linha.numero, linha.tipo = ddd, numero, tipo
        self._s.flush()

    def remover_telefone(self, id: int) -> None:
        self._s.execute(delete(Telefone).where(Telefone.id == id))
