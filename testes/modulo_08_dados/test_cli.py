from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from sar.modulo_08_dados import cli
from sar.modulo_08_dados.cli import SENHAS, comandos_usuarios

SQL = (Path(__file__).resolve().parents[2] / "sar" / "modulo_08_dados" / "usuarios_banco.sql").read_text(
    encoding="utf-8"
)
SENHAS_TESTE = {marcador: f"senha-de-teste-{usuario}" for marcador, usuario in SENHAS.items()}


@pytest.mark.requisito("DD-58")
def test_substitui_as_senhas_e_remove_comentarios() -> None:
    comandos = comandos_usuarios(SQL, SENHAS_TESTE)
    assert all("--" not in c and "{{" not in c for c in comandos)
    assert all(c.split()[0] in ("CREATE", "GRANT") for c in comandos)
    criacoes = [c for c in comandos if c.startswith("CREATE USER")]
    assert len(criacoes) == 3
    assert "IDENTIFIED BY 'senha-de-teste-sar_web'" in criacoes[0]


@pytest.mark.requisito("DD-58")
def test_comando_com_comentario_no_fim_da_linha_continua_inteiro() -> None:
    comandos = comandos_usuarios(SQL, SENHAS_TESTE)
    assert "GRANT INSERT ON sar.municipio          TO 'sar_web'@'%'" in comandos


@pytest.mark.requisito("DD-58")
@pytest.mark.parametrize("senha", ["curta", "com'aspas-e-tamanho-ok", "com espaço e tamanho ok"])
def test_recusa_senha_que_quebraria_o_sql(senha: str) -> None:
    with pytest.raises(ValueError) as erro:
        comandos_usuarios(SQL, {**SENHAS_TESTE, "{{SENHA_WEB}}": senha})
    assert senha not in str(erro.value)


@pytest.mark.requisito("DD-58")
def test_recusa_marcador_sem_senha() -> None:
    with pytest.raises(ValueError):
        comandos_usuarios(SQL, {"{{SENHA_WEB}}": "senha-de-teste-sar_web"})


class ErroDriver(Exception):
    pass


@pytest.mark.requisito("DD-81")
def test_falha_mostra_so_tipo_e_restricao_nunca_o_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def falha(_alvo: str) -> None:
        raise IntegrityError(
            "CREATE USER 'sar_web' IDENTIFIED BY 'senha-secreta-123'",
            {},
            ErroDriver(1062, "Duplicate entry 'senha-secreta-123' for key 'usuario.uq_usuario__login'"),
        )

    monkeypatch.setattr(cli, "migrar", falha)
    assert cli.main(["migrar"]) == 1
    saida = capsys.readouterr()
    assert "erro=IntegrityError" in saida.err
    assert "restricao=uq_usuario__login" in saida.err
    assert "senha-secreta-123" not in saida.out + saida.err
