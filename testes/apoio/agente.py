"""Apoio dos testes do agente de captura: certificados gerados na hora (a raiz da clínica e o do servidor), um servidor
do SAR falso em HTTPS que guarda o que recebe, e um scanner falso com páginas BMP fictícias. Nada é baixado."""

from __future__ import annotations

import io
import ipaddress
import json
import ssl
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from agente_captura.scanner import Papel, ScannerIndisponivel, SemPapel
from testes.apoio import corpus


# ------------------------------------------------------------------ certificados
@dataclass(frozen=True, slots=True)
class Certificados:
    raiz: Path  # o que a estação fixa
    servidor: Path
    chave: Path


def _nome(texto: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, texto)])


def gerar_certificados(pasta: Path, nome_raiz: str = "Autoridade Fictícia da Clínica") -> Certificados:
    pasta.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(UTC)
    chave_raiz = ec.generate_private_key(ec.SECP256R1())
    raiz = (
        x509.CertificateBuilder().subject_name(_nome(nome_raiz)).issuer_name(_nome(nome_raiz))
        .public_key(chave_raiz.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave_raiz.public_key()), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                     encipher_only=False, decipher_only=False), critical=True)
        .sign(chave_raiz, hashes.SHA256())
    )  # fmt: skip
    chave = ec.generate_private_key(ec.SECP256R1())
    servidor = (
        x509.CertificateBuilder().subject_name(_nome("127.0.0.1")).issuer_name(raiz.subject)
        .public_key(chave.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=30))
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(chave_raiz.public_key()), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                       critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(chave_raiz, hashes.SHA256())
    )  # fmt: skip
    caminhos = Certificados(pasta / "raiz.crt", pasta / "servidor.crt", pasta / "servidor.key")
    caminhos.raiz.write_bytes(raiz.public_bytes(serialization.Encoding.PEM))
    caminhos.servidor.write_bytes(servidor.public_bytes(serialization.Encoding.PEM))
    caminhos.chave.write_bytes(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))  # fmt: skip
    return caminhos


# ------------------------------------------------------------------ servidor do SAR falso
@dataclass
class Registro:
    token: str = "token-valido"
    paginas: dict[int, bytes] = field(default_factory=dict)
    concluidas: list[int] = field(default_factory=list)  # número de páginas de cada conclusão
    falhas: dict[int, int] = field(default_factory=dict)  # página → quantas vezes falhar antes de aceitar
    tentativas: dict[int, int] = field(default_factory=dict)


class _Tratador(BaseHTTPRequestHandler):
    server: ServidorSarFalso

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _resposta(self, status: int, corpo: dict[str, str] | None = None) -> None:
        dados = json.dumps(corpo).encode() if corpo else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _autorizado(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.registro.token}"

    def do_PUT(self) -> None:
        corpo = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        numero = int(self.path.rsplit("/", 1)[1])
        registro = self.server.registro
        registro.tentativas[numero] = registro.tentativas.get(numero, 0) + 1
        if registro.falhas.get(numero, 0) > 0:
            registro.falhas[numero] -= 1
            if registro.falhas[numero] % 2:
                self.close_connection = True  # queda de conexão, sem resposta
                return
            self._resposta(503)  # serviço fora do ar momentaneamente
            return
        if not self._autorizado():
            self._resposta(403, {"erro": "acesso"})
            return
        registro.paginas[numero] = corpo
        self._resposta(204)

    def do_POST(self) -> None:
        corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if not self._autorizado():
            self._resposta(403, {"erro": "acesso"})
            return
        self.server.registro.concluidas.append(int(corpo["paginas"]))
        self._resposta(204)


class ServidorSarFalso(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, certificados: Certificados) -> None:
        super().__init__(("127.0.0.1", 0), _Tratador)
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(certificados.servidor, certificados.chave)
        self.socket = contexto.wrap_socket(self.socket, server_side=True)
        self.registro = Registro()

    @property
    def endereco(self) -> str:
        return f"https://127.0.0.1:{self.server_address[1]}"

    def iniciar(self) -> ServidorSarFalso:
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


# ------------------------------------------------------------------ scanner falso
def pagina_bmp(semente: int) -> bytes:
    """Uma folha fictícia como o driver entrega: BMP em tons de cinza (DD-77)."""
    saida = io.BytesIO()
    corpus.pagina_ficticia(semente).save(saida, format="BMP")
    return saida.getvalue()


@dataclass
class ScannerFalso:
    folhas: int = 1  # no alimentador
    indisponivel: bool = False
    chamadas: list[Papel] = field(default_factory=list)
    entregues: int = 0
    liberar: threading.Event | None = None  # se houver, espera por ele antes da primeira página
    intervalo: float = 0.0  # entre as folhas, como o scanner real (2,8 a 6,9 s na DCP-L2540DW)

    def paginas(self, papel: Papel) -> Iterator[bytes]:
        self.chamadas.append(papel)
        if self.indisponivel:
            raise ScannerIndisponivel()
        if self.liberar is not None:
            self.liberar.wait(5)
        total = 1 if papel == "vidro" else self.folhas
        if total == 0:
            raise SemPapel()
        for numero in range(1, total + 1):
            if numero > 1 and self.intervalo:
                time.sleep(self.intervalo)
            self.entregues += 1
            yield pagina_bmp(numero)
