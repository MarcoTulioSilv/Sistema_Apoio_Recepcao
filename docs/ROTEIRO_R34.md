# Roteiro do teste do R-34 — agente de captura, scanner e webcam

**Objetivo.** Confirmar, no computador e no scanner reais da recepção, que a captura funciona como o
DAS (AD-17) e o DDS (DD-39) preveem: digitalizar pelo vidro e pelo alimentador **sem gravar arquivo**
(SEG-28), o Chrome falar com o agente local, e a webcam funcionar na página. O resultado também calibra
os limites de processamento (§10.1 do DDS).

**Duração estimada:** 30 a 45 minutos.

**Regra do teste:** usar só folhas **sem dado de paciente** — uma página de texto qualquer impressa,
um formulário em branco, uma folha com tabela. Nada do que é digitalizado é salvo em disco.

---

## 0. Preparação

1. Copie a pasta `teste-r34` para a estação da recepção, por exemplo em `C:\teste-r34`.
2. Abra o **PowerShell** nessa pasta:

   ```powershell
   cd C:\teste-r34
   ```

3. Confira se o Python está instalado:

   ```powershell
   py --version
   ```

   Se não estiver, instale e abra um PowerShell novo:

   ```powershell
   winget install Python.Python.3.13
   ```

4. Instale a biblioteca que conversa com o WIA:

   ```powershell
   py -m pip install -r requirements.txt
   ```

5. Coloque no scanner algumas folhas de teste: uma no vidro e três ou mais no alimentador.

---

## 1. Diagnóstico da estação

```powershell
powershell -ExecutionPolicy Bypass -File .\r34_diagnostico.ps1
```

**Anote:**

| Item | Onde ver | Esperado |
|---|---|---|
| Modelo do scanner | "Dispositivos WIA", coluna Nome | Aparece o scanner da recepção. Confira com a etiqueta do equipamento |
| Driver WIA | "Dispositivos WIA" | Pelo menos um item com Tipo = 1 (scanner) |
| Versão do Chrome | "Chrome" | Qualquer versão; ela importa para o passo 4 |
| Python e pywin32 | "Python", "pywin32" | Versão 3.12 ou maior; "instalado" |
| IP da estação | "Endereços IPv4" | O endereço da rede da clínica |

Se o scanner **não aparecer em "Dispositivos WIA"**, mas aparecer em "Dispositivos de imagem (PnP)",
o driver instalado é só TWAIN. Baixe o driver completo do site do fabricante, que costuma incluir o
WIA, e repita este passo. Se o fabricante não oferecer WIA, pare aqui e me avise: isso muda a AD-17.

---

## 2. Digitalização direta pelo WIA

Primeiro sem o navegador, para separar problema de scanner de problema de navegador.

```powershell
py r34_scanner.py --listar
py r34_scanner.py --modo vidro
py r34_scanner.py --modo alimentador
py r34_scanner.py --modo alimentador --formato jpeg
py r34_scanner.py --modo vidro --cor cor
```

Cada comando mostra o número de páginas, o tamanho de cada uma e o tempo. Os números ficam
acumulados em `resultado_r34_scanner.json`; nenhuma imagem é salva.

**Anote:**

| Verificação | Esperado |
|---|---|
| Vidro, tons de cinza, 300 dpi | 1 página, sem erro |
| Alimentador com 3 ou mais folhas | Todas as folhas numa só execução, uma página por folha |
| Alimentador vazio | Mensagem "Alimentador sem papel", sem travar |
| Formato efetivo | PNG ou JPEG. Se aparecer "bmp", o driver não oferece os outros formatos, e a conversão passa a ser do servidor |
| Tamanho por página | Anote o maior valor; ele define o limite de tamanho |
| Tempo por página | Anote; ele entra no RNF-208 (30 s da captura à conferência) |

**Se der erro no alimentador** dizendo que o driver não aceitou selecionar o alimentador, anote a
mensagem completa. Alguns drivers mais novos expõem o alimentador de outro jeito, e o agente precisa
ser ajustado para esse caso.

---

## 3. Agente e Chrome — Fase A (página em `localhost`)

1. Suba o agente com o scanner:

   ```powershell
   py r34_agente.py
   ```

   Se o Firewall do Windows perguntar, **permita só em redes privadas**. O terminal mostra os dois
   endereços da página, para a Fase A e para a Fase B. Deixe essa janela aberta.

2. No **Chrome**, abra:

   ```
   http://localhost:8000/r34_teste.html
   ```

3. Na página, faça na ordem:
   - **1. Verificar agente:** deve aparecer "Agente respondeu".
   - **2. Digitalizar:** pelo vidro e depois pelo alimentador, em PNG e em JPEG. As miniaturas aparecem
     na página.
   - **3. Webcam:** Abrir câmera, permitir o acesso quando o Chrome pedir, Capturar foto.
4. Copie o texto do quadro **4. Resultado para enviar**.

**Anote também:** se o Chrome mostrou algum **pedido de permissão** (por exemplo, para acessar
dispositivos na rede local) e o texto exato do pedido.

---

## 4. Agente e Chrome — Fase B (página pelo IP da rede)

Na produção, a página do SAR vem do servidor da clínica, por um endereço da rede local, e não de
`localhost`. Esta fase imita isso.

1. Com o agente ainda rodando, abra no Chrome o segundo endereço mostrado no terminal:

   ```
   http://<IP-da-estação>:8000/r34_teste.html
   ```

2. Repita **Verificar agente**, **Digitalizar** (só pelo vidro) e **Abrir câmera**.
3. Copie de novo o texto do quadro 4.

**O que esperar.** Aqui a página está em HTTP comum, fora de um contexto seguro. É provável que o
Chrome **bloqueie** a chamada ao agente e a câmera. Isso não é falha do teste: confirma que a produção
precisa da página em **HTTPS**, com o certificado da autoridade interna que o DAS já prevê. O que
interessa anotar é exatamente o que o Chrome fez: bloqueou, pediu permissão ou deixou passar.

No terminal do agente, cada chamada aparece com a origem e se o Chrome pediu acesso à rede local.
Copie essas linhas também.

---

## 5. O que me enviar

Cole na conversa:

1. O conteúdo de `diagnostico_r34.txt`.
2. O conteúdo de `resultado_r34_scanner.json`.
3. O texto do quadro 4 da página, da Fase A e da Fase B.
4. As linhas do terminal do agente.
5. Qualquer pedido de permissão ou mensagem de erro do Chrome, com o texto exato.

Nenhum desses arquivos contém imagem nem dado de paciente.

---

## 6. Como o resultado será usado

| Resultado | Consequência |
|---|---|
| Tudo funciona na Fase A | AD-17 confirmada. Escrevo o protocolo do agente (item 5 da §16 do DDS) |
| Fase B bloqueada | Esperado. Confirma HTTPS obrigatório na página; entra no protocolo |
| Fase B pede permissão | A permissão é concedida uma vez na estação, na implantação; entra no manual de operação |
| Alimentador falha | Ajuste do agente para o modo de alimentador do driver; se não houver jeito pelo WIA, avaliamos o TWAIN e revisamos a AD-17 |
| Scanner sem WIA | AD-17 revisada antes da construção (R-34 materializado) |
| Tamanhos e tempos | Viram os limites do §10.1 do DDS: tamanho máximo com folga sobre a maior página observada, e o tempo comparado aos 30 s do RNF-208 |

Para encerrar o agente, use **Ctrl+C** no terminal.
