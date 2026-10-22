# Instalação do agente de captura e medição dos 30 s

**Objetivo.** Instalar o agente de captura na estação da recepção (DDS §8.5) e medir, com o scanner real, o tempo
do clique em "Digitalizar" até a tela mostrar "Conferir agora" (RNF-208: até 30 s, A4 a 300 dpi).

**Duração estimada:** 30 minutos.

**Regra:** na medição, use só folhas **sem dado de paciente** (página de texto qualquer, formulário em branco) e um
paciente **fictício** cadastrado para o teste.

---

## 0. O que levar

- `sar-agente.exe`, gerado na máquina de desenvolvimento (`docs\comandos.md`, seção 8), num pen drive.
- Na produção, também o certificado raiz da autoridade interna da clínica (`raiz.crt`). Na homologação, não precisa.

Todos os comandos abaixo são no **PowerShell como administrador** na estação, salvo quando indicado.

---

## 1. Programa

```powershell
New-Item -ItemType Directory -Force "C:\Program Files\SAR" | Out-Null
Copy-Item "E:\sar-agente.exe" "C:\Program Files\SAR\sar-agente.exe"    # E: é o pen drive; ajuste a letra
```

## 2. Configuração (editável só pelo TI)

```powershell
New-Item -ItemType Directory -Force "C:\ProgramData\SAR" | Out-Null
notepad "C:\ProgramData\SAR\agente.json"
```

**Homologação** (medição de agora, com o SAR rodando na máquina de desenvolvimento em HTTP, DD-100):

```json
{
  "servidor": "http://IP-DA-MAQUINA-DE-DESENVOLVIMENTO:8080",
  "scanner": "Brother DCP-L2540DW",
  "porta": 47830,
  "desenvolvimento": true
}
```

**Produção** (Incremento 8, com HTTPS e a autoridade interna):

```json
{
  "servidor": "https://sar.clinica.local",
  "certificado_raiz": "C:\\ProgramData\\SAR\\raiz.crt",
  "scanner": "Brother DCP-L2540DW",
  "porta": 47830
}
```

O nome do scanner é exatamente o que aparece em "Dispositivos WIA" no diagnóstico do R-34 (`Brother DCP-L2540DW`).
O certificado raiz precisa ter os identificadores de chave (Subject e Authority Key Identifier): o agente usa a
conferência estrita de certificados do Python. Uma autoridade criada com o OpenSSL atual já os tem.

Depois de salvar, tire a permissão de escrita da recepção (os grupos pelos códigos, que valem em qualquer idioma do
Windows: administradores, sistema e usuários):

```powershell
icacls "C:\ProgramData\SAR" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX"
```

## 3. Início automático no logon

O agente precisa da sessão do Windows da recepção (o WIA só funciona com usuário logado). Atalho na pasta de
inicialização de todos os usuários:

```powershell
$atalho = (New-Object -ComObject WScript.Shell).CreateShortcut("C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\SAR - agente de captura.lnk")
$atalho.TargetPath = "C:\Program Files\SAR\sar-agente.exe"
$atalho.WorkingDirectory = "C:\Program Files\SAR"
$atalho.Save()
```

Não precisa de regra no Firewall: o agente escuta só em `127.0.0.1`, que nenhuma outra máquina alcança.

## 4. Conferir (no PowerShell comum, como a recepção)

```powershell
Start-Process "C:\Program Files\SAR\sar-agente.exe"
Start-Sleep 3
Test-NetConnection 127.0.0.1 -Port 47830 | Select-Object TcpTestSucceeded     # deve dar True
Get-Content "$env:LOCALAPPDATA\SAR\agente.log" -Tail 5                         # deve ter agente.iniciado
```

Se o log disser `configuracao.invalida`, a linha diz o que corrigir no `agente.json`.

---

## 5. Medição dos 30 s (homologação)

**Na máquina de desenvolvimento** (onde o SAR roda), dois terminais preparados como na seção 1 do
`docs\comandos.md`, com o Tesseract ligado:

```powershell
# terminal 1: o SAR aceitando conexões da rede local, com a origem pelo IP desta máquina
$env:SAR_WEB_HOST = "0.0.0.0"
$env:SAR_ORIGEM = "http://IP-DA-MAQUINA-DE-DESENVOLVIMENTO:8080"
python -m sar.wsgi
```

```powershell
# terminal 2
sar worker
```

Libere a porta 8080 só na rede privada (PowerShell como administrador, uma vez):

```powershell
New-NetFirewallRule -DisplayName "SAR desenvolvimento (8080)" -Direction Inbound -Protocol TCP -LocalPort 8080 -Profile Private -Action Allow
```

**Na estação:** no Chrome, abra `http://IP-DA-MAQUINA-DE-DESENVOLVIMENTO:8080`, entre, abra a ficha do paciente
fictício e clique em "Digitalizar documento".

| # | Teste | Como medir | Anote |
|---|---|---|---|
| 1 | Vidro, 1 folha, três vezes | Do clique em "Digitalizar" até aparecer "Conferir agora" | Os três tempos |
| 2 | Alimentador, 3 folhas | Idem | O tempo e se vieram 3 páginas na conferência |
| 3 | Alimentador vazio | Clique em "Digitalizar" sem papel | A mensagem (esperada: "Coloque as folhas no alimentador.") |
| 4 | Agente fechado | Feche o agente (Gerenciador de Tarefas) e clique em "Digitalizar" | A mensagem (esperada: "O programa de digitalização não respondeu…") |

Depois de cada teste, guarde ou rejeite na conferência, para a fila não acumular. A foto pela câmera **não** abre
na homologação em HTTP: o navegador só libera a câmera em HTTPS (DD-80), que chega com a implantação.

**Me envie:** a tabela preenchida e as últimas linhas de `$env:LOCALAPPDATA\SAR\agente.log` da estação (só têm
data, páginas, tempos e resultado).

---

## 6. Problemas comuns

| Sintoma | Causa provável e o que fazer |
|---|---|
| "Scanner indisponível" | O nome no `agente.json` não é o do WIA, o scanner está desligado ou outro programa o usa. Confira o nome no diagnóstico do R-34 |
| "O programa de digitalização não respondeu…" | O agente não está aberto, ou a porta é outra. Rode o passo 4 |
| Log com `servidor.porta_ocupada` | Já há um agente aberto nesta sessão. Feche o outro |
| "A conexão com o servidor falhou" | A máquina do SAR não responde na rede: confira o IP, o Firewall (porta 8080) e se o SAR está rodando |
| "A digitalização expirou ou foi cancelada" | Passaram mais de 10 minutos desde a abertura, ou ela foi cancelada na tela. Clique em "Digitalizar" de novo |

Para desinstalar: apague o atalho da inicialização, `C:\Program Files\SAR` e `C:\ProgramData\SAR`.
