from __future__ import annotations

from typing import cast

import pytest

from sar.nucleo.eventos import Barramento, CadeiaDivergente, UsuarioInativado
from sar.nucleo.uow import UnidadeDeTrabalho

UOW = cast(UnidadeDeTrabalho, object())


@pytest.mark.requisito("DD-15")
def test_despacha_so_para_quem_assinou_o_tipo_na_ordem_de_registro() -> None:
    barramento = Barramento()
    chamadas: list[str] = []
    barramento.assinar(UsuarioInativado, lambda _uow, e: chamadas.append(f"a{e.usuario_id}"))
    barramento.assinar(UsuarioInativado, lambda _uow, e: chamadas.append(f"b{e.usuario_id}"))
    barramento.assinar(CadeiaDivergente, lambda _uow, _e: chamadas.append("outro"))

    barramento.despachar(UOW, UsuarioInativado(usuario_id=7))

    assert chamadas == ["a7", "b7"]


@pytest.mark.requisito("DD-15")
def test_falha_do_manipulador_chega_a_quem_despachou() -> None:
    barramento = Barramento()

    def falha(_uow: UnidadeDeTrabalho, _e: UsuarioInativado) -> None:
        raise RuntimeError("manipulador falhou")

    barramento.assinar(UsuarioInativado, falha)
    with pytest.raises(RuntimeError):
        barramento.despachar(UOW, UsuarioInativado(usuario_id=1))


@pytest.mark.requisito("DD-15")
def test_evento_sem_assinante_nao_faz_nada() -> None:
    Barramento().despachar(UOW, UsuarioInativado(usuario_id=1))
