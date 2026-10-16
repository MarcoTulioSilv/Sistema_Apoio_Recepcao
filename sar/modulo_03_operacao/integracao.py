"""O que o MOD-03 oferece às portas dos outros módulos (DDS §7.8), ligado na raiz de composição (DD-02)."""

from __future__ import annotations

from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.nucleo.uow import UnidadeDeTrabalho


class VerificadorUsoImplantacao:
    """A data de implantação trava a partir da primeira sessão confirmada (DD-51)."""

    parametro = "data_implantacao"

    def em_uso(self, uow: UnidadeDeTrabalho) -> bool:
        return uow.repositorio(RepositorioOperacao).alguma_confirmada()
