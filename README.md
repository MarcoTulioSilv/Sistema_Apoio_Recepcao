# SAR — Sistema de Apoio à Recepção

Sistema web de apoio à recepção do Centro de Uro-Nefrologia de Jataí-GO. **Não é prontuário eletrônico.**
Todo dado de paciente é dado pessoal sensível de saúde (LGPD, art. 11): nenhum dado real entra neste
repositório, nos testes ou nos logs.

- Requisitos, arquitetura, design e plano de testes: [`docs/`](docs/)
- Ordem de construção e estado atual: [`docs/transicao-macroentrega-IV.md`](docs/transicao-macroentrega-IV.md)
- Regras do dia a dia e comandos: [`CLAUDE.md`](CLAUDE.md)

## Ambiente de desenvolvimento

Pré-requisitos: Windows com Git Bash, Python 3.14 e Docker Desktop.

```bash
py -3.14 -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev]"
python scripts/criar_segredos_dev.py
docker compose up -d --wait mysql
export SAR_SEGREDOS="$PWD/segredos" SAR_BANCO_PORTA=3307
sar migrar && sar criar-usuarios-banco
pytest testes -m "not integracao and not sistema"
```

Os demais comandos — integração, sistema, Tailwind, verificação do esquema e rastreabilidade — estão na
seção "Comandos" do `CLAUDE.md`. O pipeline de integração contínua (`.github/workflows/ci.yml`) roda as
11 etapas do plano de testes (PT §8) a cada envio.
