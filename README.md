# SAR — Sistema de Apoio à Recepção

Sistema web de apoio à recepção de clinica médica. **Não se define como prontuário eletrônico.**
Todo dado de paciente é dado pessoal sensível de saúde (LGPD, art. 11): nenhum dado real entra neste
repositório, nos testes ou nos logs.

- Requisitos, arquitetura, design e plano de testes: [`docs/`](docs/)
- Ordem de construção e estado atual: [`docs/transicao-macroentrega-IV.md`](docs/transicao-macroentrega-IV.md)

## Comandos

Instalação, execução, testes e manutenção: [`docs/comandos.md`](docs/comandos.md), o lugar único de todos os
comandos do projeto.

O pipeline de integração contínua (`.github/workflows/ci.yml`) roda as 11 etapas do plano de testes
(PT §8) a cada envio.
