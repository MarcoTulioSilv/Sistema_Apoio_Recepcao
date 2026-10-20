"""Ingestão de ponta a ponta com o banco (DDS §8.3, §8.4): web (sar_web) e worker (sar_worker), quarentena e cofre
nas pastas do teste. CT-DOC-01 (pelo worker), 02 (desfecho), 04, 05, 06, 07; DD-05, DD-33, DD-34, DD-37, DD-95,
DD-96; SEG-01, SEG-06, SEG-12, SEG-27."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pikepdf
import pytest
from sqlalchemy import Engine, text

from sar.modulo_04_documentos.contrato import EstadoIngestao, IngestaoAberta
from sar.modulo_04_documentos.ingestao import RECONSTRUIDO, hash_token
from sar.modulo_08_dados.interfaces.documentos import RepositorioDocumentos
from sar.nucleo.contexto import Perfil
from sar.nucleo.erros import AcessoNegado, IntegridadeViolada, RegraViolada
from testes.apoio import corpus
from testes.apoio.cadastro import AGORA, INICIO, dados_completos, pessoa
from testes.apoio.cadastro import montar as montar_cadastro
from testes.apoio.documentos import Documentos, montar
from testes.apoio.fabrica import Fabrica, PacienteFicticio
from testes.apoio.relogio_controlado import RelogioControlado

pytestmark = pytest.mark.integracao


@pytest.fixture
def docs(
    cadastro_zerado: dict[str, int], engine_web: Engine, engine_worker: Engine, tmp_path: Path
) -> Iterator[Documentos]:
    yield montar(engine_web, engine_worker, tmp_path, RelogioControlado(AGORA))


@pytest.fixture
def paciente(cadastro_zerado: dict[str, int], engine_web: Engine, fabrica: Fabrica) -> int:
    return montar_cadastro(engine_web).pacientes.criar(pessoa(cadastro_zerado), dados_completos(fabrica), INICIO)


def _linha(engine: Engine, sql: str, **parametros: object) -> tuple[object, ...]:
    with engine.connect() as c:
        linha = c.execute(text(sql), parametros).first()
    assert linha is not None
    return tuple(linha)


def _estado(docs: Documentos, aberta: IngestaoAberta, ids: dict[str, int]) -> EstadoIngestao:
    return docs.ingestao.situacao(pessoa(ids), aberta.id).estado


# ------------------------------------------------------------------ caminho feliz
@pytest.mark.requisito("CT-DOC-04", "SEG-27", "DD-37", "DD-38", "SEG-15", "RF-701", "RF-707")
def test_captura_processamento_conferencia_e_incorporacao(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], engine_migracao: Engine, sem_tesseract: None
) -> None:
    ids = cadastro_zerado
    aberta = docs.capturar(pessoa(ids), paciente, "declaracao_troca", [corpus.png(), corpus.jpeg()], vinculo="T-1")
    assert _estado(docs, aberta, ids) is EstadoIngestao.RECEBIDA
    assert docs.worker.processar_proxima() and not docs.worker.processar_proxima()  # uma só na fila
    conferencia = docs.ingestao.conferir(pessoa(ids), aberta.id)
    assert conferencia.situacao.estado is EstadoIngestao.AGUARDANDO_CONFERENCIA and conferencia.situacao.paginas == 2
    assert conferencia.campos == () and conferencia.vinculo == "T-1"
    reconstruido, formato = docs.ingestao.pagina_em_conferencia(pessoa(ids), aberta.id)
    assert formato == "pdf" and len(pikepdf.open(io.BytesIO(reconstruido)).pages) == 2

    documento_id = docs.ingestao.incorporar(pessoa(ids), aberta.id)
    assert _estado(docs, aberta, ids) is EstadoIngestao.INCORPORADA
    assert docs.quarentena.ingestoes() == []  # apagada depois do commit
    arquivo, chave, nonce, hash_, prova, versao, paginas = _linha(
        engine_migracao,
        "SELECT arquivo, chave_cifrada, nonce, hash_sha256, prova_encadeamento, versao, paginas FROM documento"
        " WHERE id = :d", d=bytes.fromhex(documento_id),
    )  # fmt: skip
    assert (versao, paginas) == (1, 2)
    lido = docs.cofre.ler(bytes.fromhex(documento_id), str(arquivo), bytes(chave), bytes(nonce), str(hash_))  # type: ignore[arg-type]
    assert lido == reconstruido
    [hash_registro] = _linha(engine_migracao, "SELECT hash_registro FROM auditoria WHERE operacao ="
                             " 'documento.ingestao.incorporar' AND entidade_id = :d", d=documento_id)  # fmt: skip
    assert prova == hash_registro  # DD-37: prova de encadeamento na fase de commit da auditoria


@pytest.mark.requisito("SEG-10", "DC-07", "RF-711")
def test_foto_pela_webcam(docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]) -> None:
    ids = cadastro_zerado
    aberta = docs.capturar(pessoa(ids), paciente, "foto_paciente", [corpus.foto_com_exif()], origem="webcam")
    docs.worker.processar_proxima()
    foto, formato = docs.ingestao.pagina_em_conferencia(pessoa(ids), aberta.id)
    assert formato == "jpeg" and foto.startswith(b"\xff\xd8\xff") and b"Ficticia" not in foto
    docs.ingestao.incorporar(pessoa(ids), aberta.id)


@pytest.mark.requisito("SEG-15", "INV-06")
def test_mesmo_conteudo_nao_entra_duas_vezes(docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]) -> None:
    """O hash do documento é único (§8.7): a mesma foto, reconstruída igual, é recusada com motivo, não com erro de
    banco, e nada sobra no cofre."""
    ids = cadastro_zerado
    primeira = docs.capturar(pessoa(ids), paciente, "foto_paciente", [corpus.foto_com_exif()], origem="webcam")
    segunda = docs.capturar(pessoa(ids), paciente, "foto_paciente", [corpus.foto_com_exif()], origem="webcam")
    docs.worker.processar_proxima()
    docs.worker.processar_proxima()
    docs.ingestao.incorporar(pessoa(ids), primeira.id)
    with pytest.raises(RegraViolada) as erro:
        docs.ingestao.incorporar(pessoa(ids), segunda.id)
    assert erro.value.codigo == "documento.repetido"
    assert len([p for p in docs.cofre._raiz.rglob("*") if p.is_file()]) == 1
    docs.ingestao.rejeitar(pessoa(ids), segunda.id, "tipo_errado")  # a recepcionista encerra pela rejeição


# ------------------------------------------------------------------ abertura
@pytest.mark.requisito("DD-36", "RF-708", "INV-06")
def test_abertura_confere_tipo_origem_paciente_e_versao(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], engine_migracao: Engine, sem_tesseract: None
) -> None:
    contexto = pessoa(cadastro_zerado)
    for tipo, origem, codigo in (("nao_existe", "scanner", "tipo.inexistente"),
                                 ("foto_paciente", "scanner", "tipo.origem"),
                                 ("cartao_sus", "webcam", "tipo.origem")):  # fmt: skip
        with pytest.raises(RegraViolada) as erro:
            docs.ingestao.abrir(contexto, paciente, tipo, origem)
        assert erro.value.codigo == codigo
    primeira = docs.capturar(contexto, paciente, "cartao_sus", [corpus.png()])
    docs.worker.processar_proxima()
    v1 = docs.ingestao.incorporar(contexto, primeira.id)
    outra_pagina = corpus.em_formato(corpus.pagina_ficticia(2), "PNG")
    segunda = docs.capturar(contexto, paciente, "cartao_sus", [outra_pagina], substitui_id=v1)
    docs.worker.processar_proxima()
    v2 = docs.ingestao.incorporar(contexto, segunda.id)
    versao, substitui = _linha(engine_migracao, "SELECT versao, substitui_id FROM documento WHERE id = :d",
                               d=bytes.fromhex(v2))  # fmt: skip
    assert versao == 2 and substitui == bytes.fromhex(v1)
    for substituida, tipo in ((v1, "cartao_sus"), (v2, "comprovante_endereco")):  # a não vigente; outro tipo
        with pytest.raises(RegraViolada) as erro:
            docs.ingestao.abrir(contexto, paciente, tipo, "scanner", substitui_id=substituida)
        assert erro.value.codigo == "versao.substituida"
    with engine_migracao.begin() as c:
        c.execute(text("UPDATE paciente SET anulado_em = NOW(6) WHERE id = :p"), {"p": paciente})
    with pytest.raises(RegraViolada) as erro:
        docs.ingestao.abrir(contexto, paciente, "cartao_sus", "scanner")
    assert erro.value.codigo == "paciente.anulado"


@pytest.mark.requisito("DEC-55", "RF-1004", "RNF-625")
@pytest.mark.parametrize("perfil", [Perfil.ENFERMAGEM, Perfil.TI, Perfil.VISUALIZADOR])
def test_so_recepcao_e_administracao_capturam(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], perfil: Perfil
) -> None:
    with pytest.raises(AcessoNegado):
        docs.ingestao.abrir(pessoa(cadastro_zerado, perfil=perfil), paciente, "cartao_sus", "scanner")


# ------------------------------------------------------------------ token e recebimento
@pytest.mark.requisito("CT-DOC-01", "SEG-01", "DD-05", "DD-94")
def test_token_de_uso_unico_com_prazo(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    contexto = pessoa(cadastro_zerado)
    aberta = docs.ingestao.abrir(contexto, paciente, "cartao_sus", "scanner")
    [guardado] = _linha(engine_migracao, "SELECT token_hash FROM ingestao WHERE id = :i", i=bytes.fromhex(aberta.id))
    assert guardado == hash_token(aberta.token) and aberta.token not in str(guardado)  # só o hash (DD-05)
    with pytest.raises(AcessoNegado):
        docs.ingestao.receber_pagina(aberta.id, aberta.token + "x", 1, io.BytesIO(corpus.png()))
    docs.ingestao.receber_pagina(aberta.id, aberta.token, 1, io.BytesIO(corpus.png()))
    docs.ingestao.concluir(aberta.id, aberta.token, 1)
    with pytest.raises(AcessoNegado):  # reutilizado
        docs.ingestao.receber_pagina(aberta.id, aberta.token, 2, io.BytesIO(corpus.png()))
    vencida = docs.ingestao.abrir(contexto, paciente, "cartao_sus", "scanner")
    docs.relogio.avancar(timedelta(minutes=10, seconds=1))
    with pytest.raises(AcessoNegado):
        docs.ingestao.receber_pagina(vencida.id, vencida.token, 1, io.BytesIO(corpus.png()))
    with pytest.raises(AcessoNegado):  # o token de uma ingestão não serve em outra
        docs.ingestao.receber_pagina(vencida.id, aberta.token, 1, io.BytesIO(corpus.png()))


@pytest.mark.requisito("CT-DOC-01", "SEG-06", "SEG-30")
def test_recebimento_com_limites(docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]) -> None:
    aberta = docs.ingestao.abrir(pessoa(cadastro_zerado), paciente, "cartao_sus", "scanner")
    for numero, conteudo, codigo in ((1, b"x" * ((12 << 20) + 1), "arquivo.tamanho"), (0, b"x", "pagina.numero"),
                                     (31, b"x", "pagina.numero"), (1, b"", "arquivo.vazio")):  # fmt: skip
        with pytest.raises(RegraViolada) as erro:
            docs.ingestao.receber_pagina(aberta.id, aberta.token, numero, io.BytesIO(conteudo))
        assert erro.value.codigo == codigo
    assert docs.quarentena.nomes(bytes.fromhex(aberta.id)) == []
    docs.ingestao.receber_pagina(aberta.id, aberta.token, 2, io.BytesIO(corpus.png()))
    with pytest.raises(RegraViolada) as erro:  # falta a página 1
        docs.ingestao.concluir(aberta.id, aberta.token, 2)
    assert erro.value.codigo == "paginas.faltando"
    foto = docs.ingestao.abrir(pessoa(cadastro_zerado), paciente, "foto_paciente", "webcam")
    with pytest.raises(RegraViolada):  # a foto tem uma imagem só
        docs.ingestao.receber_pagina(foto.id, foto.token, 2, io.BytesIO(corpus.jpeg()))


@pytest.mark.requisito("SEG-08", "DD-34")
def test_cancelamento_apaga_a_quarentena(docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]) -> None:
    aberta = docs.ingestao.abrir(pessoa(cadastro_zerado), paciente, "cartao_sus", "scanner")
    docs.ingestao.receber_pagina(aberta.id, aberta.token, 1, io.BytesIO(corpus.png()))
    docs.ingestao.cancelar(pessoa(cadastro_zerado), aberta.id)
    assert _estado(docs, aberta, cadastro_zerado) is EstadoIngestao.CANCELADA and docs.quarentena.ingestoes() == []
    with pytest.raises(AcessoNegado):
        docs.ingestao.concluir(aberta.id, aberta.token, 1)


# ------------------------------------------------------------------ worker: recusas
@pytest.mark.requisito("CT-DOC-01", "CT-DOC-02", "SEG-12", "SEG-24", "DD-96")
def test_hostis_rejeitados_pelo_worker_sem_sobrar_nada(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], engine_migracao: Engine
) -> None:
    ids = cadastro_zerado
    casos = [(corpus.eicar(), "malware.detectado"), (corpus.pdf_com_javascript(), "pdf.conteudo_ativo"),
             (corpus.zip_minimo(), "tipo.nao_permitido")]  # fmt: skip
    for conteudo, motivo in casos:
        aberta = docs.capturar(pessoa(ids), paciente, "cartao_sus", [conteudo])
        assert docs.worker.processar_proxima()
        situacao = docs.ingestao.situacao(pessoa(ids), aberta.id)
        assert (situacao.estado, situacao.motivo) == (EstadoIngestao.REJEITADA, motivo)
    assert docs.quarentena.ingestoes() == []  # nada armazenado (SEG-12)
    [registro] = _linha(engine_migracao, "SELECT motivo FROM auditoria WHERE operacao = 'documento.ingestao.processar'"
                        " AND motivo LIKE 'malware%'")  # fmt: skip
    assert registro == "malware.detectado: Eicar-Test-Signature"  # a evidência fica na trilha (SEG-24)
    _linha(engine_migracao, "SELECT 1 WHERE (SELECT COUNT(*) FROM documento) = 0")


@pytest.mark.requisito("SEG-21", "DD-95", "SEG-09")
def test_antimalware_vencido_rejeita_e_fora_do_ar_espera(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]
) -> None:
    ids = cadastro_zerado
    docs.antimalware.fora_do_ar = True
    aberta = docs.capturar(pessoa(ids), paciente, "cartao_sus", [corpus.png()])
    assert not docs.worker.processar_proxima()
    assert _estado(docs, aberta, ids) is EstadoIngestao.RECEBIDA  # volta à fila, nunca segue sem varredura
    assert docs.quarentena.nomes(bytes.fromhex(aberta.id)) == ["p0001"]
    docs.antimalware.fora_do_ar = False
    docs.antimalware.assinaturas_em = AGORA - timedelta(hours=49)
    assert docs.worker.processar_proxima()
    situacao = docs.ingestao.situacao(pessoa(ids), aberta.id)
    assert (situacao.estado, situacao.motivo) == (EstadoIngestao.REJEITADA, "antimalware.assinaturas_vencidas")


@pytest.mark.requisito("SEG-27", "SEG-15")
def test_pagina_alterada_na_quarentena_e_rejeitada(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]
) -> None:
    aberta = docs.capturar(pessoa(cadastro_zerado), paciente, "cartao_sus", [corpus.png()])
    docs.quarentena.gravar(bytes.fromhex(aberta.id), "p0001", corpus.jpeg())  # trocada depois da conclusão
    docs.worker.processar_proxima()
    assert docs.ingestao.situacao(pessoa(cadastro_zerado), aberta.id).motivo == "hash.divergente"


@pytest.mark.requisito("SEG-27", "DD-38")
def test_reconstruido_alterado_nao_e_incorporado(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], sem_tesseract: None
) -> None:
    aberta = docs.capturar(pessoa(cadastro_zerado), paciente, "cartao_sus", [corpus.png()])
    docs.worker.processar_proxima()
    docs.quarentena.gravar(bytes.fromhex(aberta.id), RECONSTRUIDO, b"%PDF-1.7 outro")
    with pytest.raises(IntegridadeViolada):
        docs.ingestao.incorporar(pessoa(cadastro_zerado), aberta.id)


# ------------------------------------------------------------------ worker: fila, retomada e expiração
@pytest.mark.requisito("CT-DOC-05", "DD-33")
def test_worker_interrompido_retoma_do_inicio(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], sem_tesseract: None
) -> None:
    ids = cadastro_zerado
    aberta = docs.capturar(pessoa(ids), paciente, "cartao_sus", [corpus.png()])
    assert docs.worker._tomar() is not None  # tomou e "morreu" antes de processar
    assert _estado(docs, aberta, ids) is EstadoIngestao.EM_PROCESSAMENTO
    assert not docs.worker.processar_proxima()  # nada na fila
    assert docs.worker.retomar() == 1
    assert docs.worker.processar_proxima()
    assert _estado(docs, aberta, ids) is EstadoIngestao.AGUARDANDO_CONFERENCIA


@pytest.mark.requisito("DD-33")
def test_fila_com_skip_locked(docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]) -> None:
    primeira = docs.capturar(pessoa(cadastro_zerado), paciente, "cartao_sus", [corpus.png()])
    segunda = docs.capturar(pessoa(cadastro_zerado), paciente, "cartao_sus", [corpus.png()])
    executar = docs.worker._executar

    def dois_workers(uow: object) -> tuple[bytes | None, bytes | None]:
        travada = uow.repositorio(RepositorioDocumentos).tomar_da_fila()  # type: ignore[attr-defined]
        outra = executar(lambda u2: u2.repositorio(RepositorioDocumentos).tomar_da_fila())
        return (travada.id if travada else None, outra.id if outra else None)

    travada, outra = executar(dois_workers)
    assert travada != outra and {travada, outra} == {bytes.fromhex(primeira.id), bytes.fromhex(segunda.id)}


@pytest.mark.requisito("CT-DOC-06", "CT-DOC-07", "DD-34", "P-18")
def test_expiracao_em_24_horas_apaga_tudo(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], engine_migracao: Engine,
    tesseract_falso: PacienteFicticio,
) -> None:  # fmt: skip
    ids = cadastro_zerado
    esperando = docs.capturar(pessoa(ids), paciente, "cartao_sus", [corpus.png()])
    docs.worker.processar_proxima()
    aberta = docs.ingestao.abrir(pessoa(ids), paciente, "cartao_sus", "scanner")
    [candidatos] = _linha(engine_migracao, "SELECT campos_candidatos_cifrados FROM ingestao WHERE id = :i",
                          i=bytes.fromhex(esperando.id))  # fmt: skip
    assert candidatos is not None and tesseract_falso.cns.encode() not in bytes(candidatos)  # type: ignore[arg-type]
    docs.relogio.avancar(timedelta(minutes=11))
    assert docs.worker.expirar() == 1  # só a aberta, pelo prazo do token
    assert _estado(docs, aberta, ids) is EstadoIngestao.EXPIRADA
    docs.relogio.avancar(timedelta(hours=24))
    assert docs.worker.expirar() == 1
    assert _estado(docs, esperando, ids) is EstadoIngestao.EXPIRADA
    [candidatos] = _linha(engine_migracao, "SELECT campos_candidatos_cifrados FROM ingestao WHERE id = :i",
                          i=bytes.fromhex(esperando.id))  # fmt: skip
    assert candidatos is None and docs.quarentena.ingestoes() == []


@pytest.mark.requisito("CT-DOC-07", "SEG-31", "P-18", "DD-40", "RF-703", "RF-704")
def test_candidatos_na_conferencia_e_apagados_ao_concluir(
    docs: Documentos, paciente: int, cadastro_zerado: dict[str, int], engine_migracao: Engine,
    tesseract_falso: PacienteFicticio,
) -> None:  # fmt: skip
    ids = cadastro_zerado
    incorporar = docs.capturar(pessoa(ids), paciente, "cartao_sus", [corpus.png()])
    rejeitar = docs.capturar(pessoa(ids), paciente, "comprovante_endereco", [corpus.png()])
    docs.worker.processar_proxima()
    docs.worker.processar_proxima()
    [cns] = docs.ingestao.conferir(pessoa(ids), incorporar.id).campos
    assert (cns.nome, cns.valor, cns.confianca) == ("cns", tesseract_falso.cns, "alta")  # só o campo do tipo
    assert docs.ingestao.conferir(pessoa(ids), rejeitar.id).campos == ()  # o texto não tem CEP
    docs.ingestao.incorporar(pessoa(ids), incorporar.id)
    with pytest.raises(RegraViolada):
        docs.ingestao.rejeitar(pessoa(ids), rejeitar.id, "nao_gostei")
    docs.ingestao.rejeitar(pessoa(ids), rejeitar.id, "ilegivel")
    assert docs.ingestao.situacao(pessoa(ids), rejeitar.id).motivo == "conferencia.ilegivel"
    with engine_migracao.connect() as c:
        restantes = c.execute(text("SELECT COUNT(*) FROM ingestao WHERE campos_candidatos_cifrados IS NOT NULL"))
        assert restantes.scalar_one() == 0
        textos = c.execute(text("SELECT COALESCE(alteracoes, ''), COALESCE(motivo, '') FROM auditoria")).all()
    assert not any(tesseract_falso.cns in a or "SIGILOSO" in a + m for a, m in textos)  # nem na trilha
    with pytest.raises(RegraViolada):  # já encerrada
        docs.ingestao.incorporar(pessoa(ids), rejeitar.id)


@pytest.mark.requisito("DD-34", "R-41")
def test_limpeza_da_quarentena_que_sobrou(docs: Documentos, paciente: int, cadastro_zerado: dict[str, int]) -> None:
    aberta = docs.ingestao.abrir(pessoa(cadastro_zerado), paciente, "cartao_sus", "scanner")
    docs.quarentena.gravar(bytes.fromhex(aberta.id), "p0001", corpus.png())
    docs.quarentena.gravar(b"\x01" * 16, "p0001", b"sem ingestao")
    assert docs.worker.limpar_quarentena() == 1
    assert docs.quarentena.ingestoes() == [bytes.fromhex(aberta.id)]
