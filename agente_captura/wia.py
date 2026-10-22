"""Scanner pelo WIA do Windows (AD-17, DD-79), escolhido pelo nome. Validado no R-34 com a Brother DCP-1610NW e,
em 22/10/2026, com a DCP-L2540DW: o driver entrega BMP qualquer que seja o formato pedido (DD-77).

A imagem vem da transferência como bytes em memória (`FileData.BinaryData`); nunca `SaveFile` (SEG-28).
"""

from __future__ import annotations

import gc
from collections.abc import Iterator
from typing import Any

from agente_captura.scanner import Papel, ScannerIndisponivel, SemPapel

TIPO_SCANNER = 1
FORMATO_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
# Propriedades do WIA 2.0
SELECAO_DOCUMENTO = 3088  # WIA_DPS_DOCUMENT_HANDLING_SELECT
ALIMENTADOR, VIDRO = 1, 2
INTENCAO = 6146  # WIA_IPS_CUR_INTENT
CINZA = 2  # WIA_INTENT_IMAGE_TYPE_GRAYSCALE
RESOLUCAO_X, RESOLUCAO_Y = 6147, 6148
TIPO_DADOS, PROFUNDIDADE = 4103, 4104  # WIA_IPA_DATATYPE (2 = cinza), WIA_IPA_DEPTH
DPI = 300
# HRESULT do WIA
SEM_PAPEL = 0x80210003  # WIA_ERROR_PAPER_EMPTY; qualquer outro erro é scanner indisponível


def hresult(erro: BaseException) -> int:
    """O código do erro do COM, sem sinal. O pywin32 levanta com_error(hresult, texto, excepinfo, argumento); o código
    do próprio WIA vem em excepinfo[5] quando a chamada foi por IDispatch, senão no hresult."""
    argumentos: tuple[object, ...] = tuple(getattr(erro, "args", ()))
    excepinfo = argumentos[2] if len(argumentos) > 2 else None
    if isinstance(excepinfo, tuple) and len(excepinfo) > 5 and isinstance(excepinfo[5], int) and excepinfo[5]:
        return excepinfo[5] & 0xFFFFFFFF
    if argumentos and isinstance(argumentos[0], int):
        return argumentos[0] & 0xFFFFFFFF
    return 0


def _definir(propriedades: Any, identificador: int, valor: int) -> None:
    for propriedade in propriedades:
        if propriedade.PropertyID == identificador:
            propriedade.Value = valor
            return


class ScannerWia:
    def __init__(self, nome: str) -> None:
        self._nome = nome

    def _conectar(self) -> Any:
        """O dispositivo, ou None. Não levanta exceção: o traceback seguraria os objetos do COM (ver `paginas`)."""
        import win32com.client  # só existe no Windows

        gerenciador = win32com.client.Dispatch("WIA.DeviceManager")
        for informacao in gerenciador.DeviceInfos:
            if informacao.Type == TIPO_SCANNER and informacao.Properties("Name").Value == self._nome:
                try:
                    return informacao.Connect()
                except Exception:
                    return None
        return None

    def _transferir(self, dispositivo: Any) -> bytes | int:
        """A página em BMP, ou o código do erro do WIA (pelo mesmo motivo de `_conectar`)."""
        try:
            item = dispositivo.Items(1)
            for identificador, valor in ((INTENCAO, CINZA), (RESOLUCAO_X, DPI), (RESOLUCAO_Y, DPI), (TIPO_DADOS, 2),
                                         (PROFUNDIDADE, 8)):  # fmt: skip
                _definir(item.Properties, identificador, valor)
            imagem = item.Transfer(FORMATO_BMP)
            return bytes(imagem.FileData.BinaryData)
        except Exception as erro:
            return hresult(erro) or -1

    def paginas(self, papel: Papel) -> Iterator[bytes]:
        """As exceções `SemPapel` e `ScannerIndisponivel` saem daqui, sem objeto do COM no caminho: com um traceback
        segurando o dispositivo, a liberação dele depois do CoUninitialize daria erro no Windows."""
        import pythoncom  # só existe no Windows

        pythoncom.CoInitialize()  # cada captura roda numa linha de execução própria
        dispositivo = None
        falha: type[Exception] | None = None
        try:
            dispositivo = self._conectar()
            if dispositivo is None:
                falha = ScannerIndisponivel
                return
            _definir(dispositivo.Properties, SELECAO_DOCUMENTO, ALIMENTADOR if papel == "alimentador" else VIDRO)
            lidas = 0
            while True:
                pagina = self._transferir(dispositivo)
                if isinstance(pagina, int):
                    if pagina == SEM_PAPEL and lidas > 0:
                        return  # acabou o papel do alimentador
                    falha = SemPapel if pagina == SEM_PAPEL else ScannerIndisponivel
                    return
                lidas += 1
                yield pagina
                if papel == "vidro":
                    return
        finally:
            dispositivo = None
            gc.collect()
            pythoncom.CoUninitialize()
            if falha is not None:
                raise falha()
