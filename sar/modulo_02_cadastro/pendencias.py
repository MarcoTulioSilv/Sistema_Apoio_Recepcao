"""Pendências do cadastro (DDS §11.1, linhas 1, 3 e 9; DD-54) e o marco de retenção para o MOD-04 (DD-01).

Cada fonte responde ao conjunto numa consulta só (§11.3). Só recepção e administração veem estas linhas (ERS
§3.2.13); para qualquer outro perfil a fonte devolve nada, mesmo antes do filtro do MOD-07, para que dado de
paciente nunca chegue ao TI (RNF-625)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

from sar.modulo_02_cadastro.regras import CEP_NAO_VERIFICADO, chave_triade, pendencias
from sar.modulo_02_cadastro.servicos import dados_de
from sar.modulo_08_dados.interfaces.pacientes import (
    CoberturaGravada,
    PacienteGravado,
    PeriodoGravado,
    RepositorioPaciente,
)
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.documentos import DOCUMENTO_DO_EVENTO
from sar.nucleo.portas import ExigenciaChecklist, FontePendencia, ItemPendencia, MarcoRetencao, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho

PERFIS = frozenset({Perfil.RECEPCAO, Perfil.ADMINISTRACAO})

ROTULOS_CAMPOS = {
    "data_nascimento": "nascimento", "sexo": "sexo", "nome_mae": "nome da mãe", "cpf": "CPF", "cns": "CNS",
    "rg": "RG", "rg_orgao": "órgão do RG", "naturalidade_municipio": "naturalidade", "logradouro": "logradouro",
    "numero": "número", "bairro": "bairro", "municipio": "município", "cep": "CEP",
}  # fmt: skip
NOMES_EVENTO = {
    "obito": "Óbito", "alta": "Alta", "transferencia": "Transferência", "transplante": "Transplante",
    "desistencia": "Desistência",
}  # fmt: skip
NOMES_DOCUMENTO = {
    "certidao_obito": "certidão de óbito", "documento_alta": "documento de alta",
    "encaminhamento_transferencia": "encaminhamento de transferência",
    "documento_transplante": "documento do centro transplantador", "termo_interrupcao": "termo de interrupção",
}  # fmt: skip


def destino(paciente_id: int) -> str:
    return f"/pacientes/{paciente_id}"


class _Fonte:
    codigo: str
    prioridade: Prioridade

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        return self._itens(uow, None) if contexto.perfil in PERFIS else []

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        if contexto.perfil not in PERFIS or not paciente_ids:
            return []
        return self._itens(uow, paciente_ids)

    def _itens(self, uow: UnidadeDeTrabalho, ids: Sequence[int] | None) -> list[ItemPendencia]:
        raise NotImplementedError

    def _item(self, desde: datetime, descricao: str, paciente_id: int) -> ItemPendencia:
        return ItemPendencia(self.codigo, self.prioridade, desde, descricao, destino(paciente_id), paciente_id)


class FonteCadastroIncompleto(_Fonte):
    """Linha 1: campo faltante ou CEP não verificado, só de paciente em tratamento (DEC-71, §11.2)."""

    codigo = "cadastro_incompleto"
    prioridade = Prioridade.NORMAL

    def _itens(self, uow: UnidadeDeTrabalho, ids: Sequence[int] | None) -> list[ItemPendencia]:
        repositorio = uow.repositorio(RepositorioPaciente)
        em_tratamento = {p.paciente_id for p in repositorio.periodos_de(ids) if p.evento_tipo is None}
        itens = []
        for paciente in repositorio.vivos(ids):
            if paciente.id not in em_tratamento:
                continue
            faltas = pendencias(dados_de(paciente.campos), paciente.cep_verificado)
            if not faltas:
                continue
            campos = [ROTULOS_CAMPOS[f] for f in faltas if f != CEP_NAO_VERIFICADO]
            partes = [f"Faltam: {', '.join(campos)}"] if campos else []
            if CEP_NAO_VERIFICADO in faltas:
                partes.append("CEP não verificado")
            itens.append(self._item(paciente.criado_em, "; ".join(partes), paciente.id))
        return itens


class FonteEventoSemComprovante(_Fonte):
    """Linha 3: evento sem o documento exigido (DEC-53, INV-11), em qualquer situação do paciente."""

    codigo = "evento_sem_comprovante"
    prioridade = Prioridade.ALTA

    def _itens(self, uow: UnidadeDeTrabalho, ids: Sequence[int] | None) -> list[ItemPendencia]:
        itens = []
        for periodo in uow.repositorio(RepositorioPaciente).periodos_de(ids):
            if periodo.evento_tipo is None or periodo.evento_data is None or periodo.evento_documento_id is not None:
                continue
            documento = NOMES_DOCUMENTO[DOCUMENTO_DO_EVENTO[periodo.evento_tipo]]
            descricao = f"{NOMES_EVENTO[periodo.evento_tipo]} em {periodo.evento_data:%d/%m/%Y} sem {documento}"
            itens.append(self._item(_registro(periodo), descricao, periodo.paciente_id))
        return itens


class FontePossivelDuplicidade(_Fonte):
    """Linha 9: tríade coincidente ainda não descartada (INV-08). Um item para cada paciente do par; a
    comparação usa todos os pacientes, mesmo quando a pergunta é sobre alguns."""

    codigo = "possivel_duplicidade"
    prioridade = Prioridade.NORMAL

    def _itens(self, uow: UnidadeDeTrabalho, ids: Sequence[int] | None) -> list[ItemPendencia]:
        repositorio = uow.repositorio(RepositorioPaciente)
        grupos: dict[tuple[str, object, str], list[PacienteGravado]] = defaultdict(list)
        for paciente in repositorio.vivos(None):
            chave = chave_triade(paciente.campos.nome, paciente.campos.data_nascimento, paciente.campos.nome_mae)
            if chave is not None:
                grupos[chave].append(paciente)
        descartes = repositorio.descartes()
        alvo = set(ids) if ids is not None else None
        itens = []
        for grupo in grupos.values():
            for a in grupo:
                for b in grupo:
                    if a.id == b.id or (min(a.id, b.id), max(a.id, b.id)) in descartes:
                        continue
                    if alvo is None or a.id in alvo:
                        desde = max(a.criado_em, b.criado_em)
                        itens.append(self._item(desde, f"Tríade coincide com o prontuário {b.campos.prontuario}", a.id))
        return itens


def _registro(periodo: PeriodoGravado) -> datetime:
    if periodo.evento_registrado_em is not None:
        return periodo.evento_registrado_em
    if periodo.evento_data is None:
        raise RuntimeError("período sem evento")
    return datetime.combine(periodo.evento_data, time(), UTC)


FONTES: tuple[FontePendencia, ...] = (
    FonteCadastroIncompleto(),
    FonteEventoSemComprovante(),
    FontePossivelDuplicidade(),
)


class ServicoChecklist:
    """Implementa a FonteChecklist (RF-706): quem está em tratamento e se a cobertura vigente na data é de convênio.
    O MOD-04 compara com os tipos de documento presentes."""

    def exigencias(
        self, uow: UnidadeDeTrabalho, paciente_ids: Sequence[int] | None, hoje: date
    ) -> list[ExigenciaChecklist]:
        repositorio = uow.repositorio(RepositorioPaciente)
        vivos = {p.id for p in repositorio.vivos(paciente_ids)}
        abertos = [p for p in repositorio.periodos_de(paciente_ids) if p.evento_tipo is None and p.paciente_id in vivos]
        por_periodo: dict[int, list[CoberturaGravada]] = defaultdict(list)
        for cobertura in repositorio.coberturas([p.id for p in abertos]) if abertos else []:
            por_periodo[cobertura.periodo_id].append(cobertura)
        exigencias = []
        for periodo in abertos:
            vigentes = [c for c in por_periodo[periodo.id] if c.inicio <= hoje]
            atual = max(vigentes, key=lambda c: c.inicio) if vigentes else None
            desde = datetime.combine(periodo.inicio, time(), UTC)
            convenio = atual is not None and atual.convenio_id is not None
            exigencias.append(ExigenciaChecklist(periodo.paciente_id, convenio, desde))
        return exigencias


class ServicoMarcoRetencao:
    """Implementa a FonteMarcoRetencao (DD-01): em tratamento não há prazo; encerrado o último período, o marco
    do cadastro é a data do evento (o MOD-04 compara com o último documento incorporado)."""

    def marco(self, uow: UnidadeDeTrabalho, paciente_id: int) -> MarcoRetencao:
        periodos = uow.repositorio(RepositorioPaciente).periodos(paciente_id)
        if not periodos or any(p.evento_tipo is None for p in periodos):
            return MarcoRetencao(em_tratamento=bool(periodos), ultimo_encerramento=None)
        return MarcoRetencao(
            em_tratamento=False, ultimo_encerramento=max(p.evento_data for p in periodos if p.evento_data)
        )
