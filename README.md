# SAR — Sistema de Apoio à Recepção

Sistema web de apoio à recepção de clinica médica. **Não se define como prontuário eletrônico.**
Todo dado de paciente é dado pessoal sensível de saúde (LGPD, art. 11): nenhum dado real entra neste
repositório, nos testes ou nos logs.

- Requisitos, arquitetura, design e plano de testes: [`docs/`](docs/)
- Ordem de construção e estado atual: [`docs/transicao-macroentrega-IV.md`](docs/transicao-macroentrega-IV.md)

## Ambiente de desenvolvimento

Pré-requisitos: Windows com Git Bash, Python 3.14 e Docker Desktop. Rode no Git Bash com o `.venv` ativo
(`source .venv/Scripts/activate`). O banco de desenvolvimento escuta em 127.0.0.1:3307.

```bash
# Uma vez: ambiente, segredos e banco
py -3.14 -m venv .venv && pip install -e ".[dev]"   # ou o python.exe do 3.14
python scripts/criar_segredos_dev.py               # segredos/ (fora do git)
docker compose up -d --wait mysql                  # MySQL 9.7.2 sem binlog nem logs de instrução (DD-82)
export SAR_SEGREDOS="$PWD/segredos" SAR_BANCO_PORTA=3307
sar migrar                                         # migrações até head (usuário sar_migracao)
sar criar-usuarios-banco                           # sar_web, sar_worker, sar_expurgo (DD-58)

# Banco
sar reverter base && sar migrar                    # ida, volta e ida (só antes do go-live, DD-60)
docker compose exec -T mysql bash -c 'ADMIN="-uroot -p$(cat /run/secrets/mysql_root)"   WEB_SENHA=$(cat /run/secrets/sar_web) WORKER_SENHA=$(cat /run/secrets/sar_worker)   EXPURGO_SENHA=$(cat /run/secrets/sar_expurgo) bash /sar/scripts/verificar_esquema.sh'

# Qualidade (etapas 1 a 5 do pipeline)
ruff check . && ruff format --check .
mypy sar
lint-imports
bandit -q -c pyproject.toml -r sar
pip-audit --skip-editable

# Testes
pytest testes -m "not integracao and not sistema"   # unidade, rápido
pytest testes -m integracao                         # com MySQL
pytest testes -m sistema                            # Playwright (playwright install chromium, uma vez)
pytest testes --cov                                 # tudo, com cobertura (piso de 80%)

# Interface: executável standalone do Tailwind v4.3.3 em bin/ (fora do git), sem Node (AD-05)
bin/tailwindcss -i sar/web/src/sar.css -o sar/web/static/css/sar.css --minify

# Rastreabilidade: o CI usa --estrito-citacoes até a homologação; --estrito no Incremento 8
python scripts/verificar_rastreabilidade.py --estrito-citacoes

# Aplicação local
python -m sar.wsgi                                 # Waitress em 127.0.0.1:8080, logs JSON (DD-81)
```

O pipeline de integração contínua (`.github/workflows/ci.yml`) roda as 11 etapas do plano de testes
(PT §8) a cada envio.
