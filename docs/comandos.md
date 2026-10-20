# Comandos do SAR

Todo comando que se precisa saber para instalar, rodar, testar e manter o SAR em desenvolvimento.
**Este é o lugar único dos comandos:** quando um comando novo surgir ou mudar, ele é atualizado aqui.

Os exemplos usam o **PowerShell**, o terminal padrão do Windows e do VS Code. Onde o **Git Bash** é
diferente, a versão dele vem logo abaixo. Na maioria dos comandos (`sar`, `pytest`, `docker`), a sintaxe é a
mesma nos dois.

---

## 1. Antes de qualquer comando: preparar o terminal

Abra o terminal no VS Code (**Ctrl+'**) e rode:

```powershell
cd $HOME\Desktop\CC\SAR_Centro_uronefrologia
.\.venv\Scripts\Activate.ps1                 # o prompt passa a mostrar (.venv)
```

```bash
# Git Bash
cd ~/Desktop/CC/SAR_Centro_uronefrologia
source .venv/Scripts/activate
```

Depois, as variáveis de ambiente. **Elas valem só para aquele terminal:** num terminal novo, defina de novo.

```powershell
$env:SAR_SEGREDOS = "$PWD\segredos"          # onde estão as senhas e a chave (segredos/LEIA-ME.md)
$env:SAR_BANCO_PORTA = "3307"                # o MySQL do docker-compose escuta nessa porta
$env:SAR_AMBIENTE = "desenvolvimento"        # sem isso, o SAR se comporta como produção (DD-85)
```

```bash
# Git Bash
export SAR_SEGREDOS="$PWD/segredos" SAR_BANCO_PORTA=3307 SAR_AMBIENTE=desenvolvimento
```

> Erro `'export' não é reconhecido`: você está no PowerShell usando a sintaxe do Git Bash. Use `$env:`.

### Variáveis de ambiente

| Variável | Para que serve | Valor em desenvolvimento |
|---|---|---|
| `SAR_SEGREDOS` | Pasta dos segredos (senhas do banco, chave mestra) | `<projeto>\segredos` |
| `SAR_BANCO_PORTA` | Porta do MySQL | `3307` |
| `SAR_BANCO_NOME` | Banco usado: `sar` (aplicação) ou `sar_teste` (testes) | `sar` (padrão); os testes usam `sar_teste` sozinhos |
| `SAR_BANCO_HOST` | Servidor do MySQL | `127.0.0.1` (padrão) |
| `SAR_AMBIENTE` | `desenvolvimento` ou `producao` | `desenvolvimento`; sem ela, vale produção |
| `SAR_ORIGEM` | Endereço exato da página do SAR (DD-80, DD-84) | `http://127.0.0.1:8080` (padrão em desenvolvimento) |
| `SAR_SUPERUSUARIOS` | Logins que trocam de perfil pelo cabeçalho (DD-85) | o seu login; só em desenvolvimento |
| `SAR_WEB_PORTA` | Porta da aplicação | `8080` (padrão) |
| `SAR_PROXIES` | Proxies confiáveis na frente (Caddy) | `0` em desenvolvimento; `1` no servidor |
| `SAR_CLAMAV_HOST` / `SAR_CLAMAV_PORTA` | Onde o clamd escuta (SEG-09) | `127.0.0.1` e `3310` (padrão, o do compose) |
| `SAR_TESSERACT` | Executável do Tesseract, se não estiver no PATH; sem Tesseract, a extração fica desligada e a conferência é manual (RNF-702) | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| `SAR_VERAPDF` | Executável do veraPDF, se não estiver no PATH; sem ele, o teste de PDF/A é pulado (o CI roda) | `C:\verapdf\verapdf.bat` |

---

## 2. Primeira vez numa máquina

Pré-requisitos: Python 3.14 (`winget install Python.Python.3.14`), Docker Desktop e Git.

```powershell
cd $HOME\Desktop\CC\SAR_Centro_uronefrologia
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"                      # dependências do projeto e das ferramentas
playwright install chromium                  # navegador dos testes de sistema
python scripts\criar_segredos_dev.py         # gera segredos\ (fora do git); não sobrescreve
docker compose up -d --wait mysql            # sobe o MySQL 9.7.2; na primeira vez cria sar e sar_teste
docker compose up -d --wait clamav           # antimalware; na primeira vez baixa as assinaturas (alguns minutos)
```

Defina as variáveis da seção 1 e prepare os dois bancos (o da aplicação e o dos testes):

```powershell
sar migrar                                   # banco sar: todas as migrações
sar criar-usuarios-banco                     # usuários sar_web, sar_worker e sar_expurgo (DD-58)

$env:SAR_BANCO_NOME = "sar_teste"
sar migrar
sar criar-usuarios-banco
Remove-Item Env:SAR_BANCO_NOME               # volta ao banco sar
```

Executável do Tailwind (sem Node, AD-05), uma vez, na pasta `bin\` (fora do git):

```powershell
New-Item -ItemType Directory -Force bin | Out-Null
Invoke-WebRequest -Uri "https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.3/tailwindcss-windows-x64.exe" -OutFile bin\tailwindcss.exe
```

Por fim, o seu usuário de desenvolvimento (seção 5) e o CSS (seção 7).

---

## 3. Dia a dia: rodar a aplicação

```powershell
docker compose up -d --wait mysql clamav     # garante o banco e o antimalware no ar (Docker Desktop aberto)
$env:SAR_SUPERUSUARIOS = "seu.login"         # o login exato que o criar-superusuario mostrou; vários: "a,b"
python -m sar.wsgi
```

- Abra **http://127.0.0.1:8080** no navegador. Use exatamente esse endereço: com `localhost:8080`, a
  proteção contra requisição forjada (DD-84) recusa os formulários.
- O terminal fica mostrando os logs em JSON. **Ctrl+C** para o servidor.
- O superusuário escolhe o perfil no seletor "Agir como (desenvolvimento)", no cabeçalho.

Parar e voltar o banco:

```powershell
docker compose stop mysql                    # para; os dados ficam no volume
docker compose up -d --wait mysql            # sobe de novo
```

---

## 4. Banco

```powershell
sar migrar                                   # aplica as migrações até a última
sar reverter base; sar migrar                # desfaz tudo e refaz (só antes do go-live, DD-60)
sar reverter 0003                            # volta até uma migração específica
sar verificar-cadeia                         # confere a trilha de auditoria, como o job diário (§13.1)
```

Para agir no banco de testes, defina `$env:SAR_BANCO_NOME = "sar_teste"` antes (e remova depois com
`Remove-Item Env:SAR_BANCO_NOME`).

Verificação das invariantes, dos privilégios e dos logs do servidor (`verificar_esquema.sh`, 28 itens).
Roda dentro do contêiner e **insere e apaga dados**: só no banco de testes. O comando é o mesmo no
PowerShell e no Git Bash:

```powershell
docker compose exec -T mysql bash -c 'BANCO=sar_teste ADMIN="-uroot -p$(cat /run/secrets/mysql_root)" WEB_SENHA=$(cat /run/secrets/sar_web) WORKER_SENHA=$(cat /run/secrets/sar_worker) EXPURGO_SENHA=$(cat /run/secrets/sar_expurgo) bash /sar/scripts/verificar_esquema.sh'
```

Abrir o cliente do MySQL dentro do contêiner, como root:

```powershell
docker compose exec mysql bash -c 'mysql -uroot -p"$(cat /run/secrets/mysql_root)" sar'
```

---

## 5. Usuários

Superusuário de desenvolvimento (DD-85). Mostra a senha provisória, trocada na primeira entrada:

```powershell
sar criar-superusuario --nome "Seu Nome" --login seu.login     # exige SAR_AMBIENTE=desenvolvimento
```

Primeiro TI da implantação. Só funciona quando não há nenhum TI ativo, e exige confirmar que o termo de
ciência foi assinado (DEC-47). Também é a recuperação se o sistema ficar sem TI:

```powershell
sar criar-usuario-ti --nome "Nome do TI" --login login.ti --termo-assinado
```

Os demais usuários são criados pela tela do TI.

---

## 6. Testes e qualidade

Os testes usam o banco `sar_teste` sozinhos: nunca mexem no banco `sar` da aplicação. Precisam do MySQL no
ar e das variáveis `SAR_SEGREDOS` e `SAR_BANCO_PORTA` (seção 1). Os testes do antimalware usam o ClamAV do
compose e são pulados se ele estiver fora do ar; com `$env:SAR_EXIGIR_CLAMAV = "1"` (como no CI), falham.

```powershell
pytest testes -m "not integracao and not sistema"   # unidade: rápido, sem banco
pytest testes -m integracao                          # com o MySQL
pytest testes -m sistema                             # navegador (Playwright e axe-core)
pytest testes                                        # tudo
pytest testes --cov                                  # tudo, com cobertura (piso de 80%)
pytest testes\modulo_01_acesso -k sessao             # só um módulo, ou só os testes com "sessao" no nome
```

Ciclo rápido, durante o desenvolvimento de uma etapa: unidade de tudo mais todos os testes do módulo mexido
(aqui, o MOD-02). A suíte inteira roda uma vez antes de cada commit, e o pipeline do GitHub roda tudo.

```powershell
pytest testes -m "not integracao and not sistema"; pytest testes\modulo_02_cadastro
```

As mesmas etapas do pipeline do GitHub (PT §8), na ordem:

```powershell
ruff check .; ruff format --check .                  # 1. estilo
mypy sar                                             # 2. tipos
lint-imports                                         # 3. fronteiras entre módulos (25 contratos)
pip-audit --skip-editable                            # 4. dependências com vulnerabilidade
bandit -q -c pyproject.toml -r sar                   # 5. análise estática
python scripts\verificar_rastreabilidade.py --estrito-citacoes   # 11. rastreabilidade com a ERS
```

Corrigir o estilo automaticamente: `ruff format .` e `ruff check --fix .`

---

## 7. Interface (CSS)

Sempre que um modelo HTML ganhar classes novas, gere o CSS de novo:

```powershell
.\bin\tailwindcss.exe -i sar\web\src\sar.css -o sar\web\static\css\sar.css --minify
```

CSS do protótipo e do guia de componentes (`docs\prototipo\componentes.html`):

```powershell
.\bin\tailwindcss.exe -i docs\prototipo\src\sar.css -o docs\prototipo\static\css\sar.css --minify
```

---

## 8. Dados de referência

Tabela de municípios do IBGE (`dados\municipios_ibge.csv`), regerada quando o IBGE criar ou renomear
município:

```powershell
python scripts\gerar_municipios_ibge.py
```

---

## 9. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `'export' não é reconhecido` | PowerShell com sintaxe do Git Bash. Use `$env:NOME = "valor"` |
| `sar` não é reconhecido | O `.venv` não está ativo: `.\.venv\Scripts\Activate.ps1` |
| `Can't connect to MySQL` / conexão recusada | O banco não está no ar: abra o Docker Desktop e rode `docker compose up -d --wait mysql` |
| `segredo ausente` | `SAR_SEGREDOS` não definida neste terminal (seção 1) |
| Formulário dá "Forbidden" (403) | Página aberta como `localhost`. Use `http://127.0.0.1:8080` |
| Tela sem estilo | Falta gerar o CSS (seção 7) |
| `login_repetido` ao criar superusuário | O usuário já existe; entre com ele. Esqueceu a senha: um usuário TI a redefine na tela de usuários |
| Servidor não sobe: `SAR_SUPERUSUARIOS cita login que não existe` | A grafia na variável é diferente da gravada (ponto e sublinhado contam). Use o login que o `criar-superusuario` mostrou como "Login gravado" |
| O seletor "Agir como" não aparece | O login não está em `SAR_SUPERUSUARIOS`, ou o servidor foi iniciado antes de mudar a variável: pare com Ctrl+C e suba de novo no mesmo terminal |
| Esqueci a senha e não há outro TI | Crie outro superusuário, entre com ele, escolha TI no seletor e redefina a senha na tela de Usuários |
| `Activate.ps1 não pode ser carregado` | Política de execução do PowerShell: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, uma vez |
