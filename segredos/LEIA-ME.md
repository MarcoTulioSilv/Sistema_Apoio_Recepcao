# Segredos

Esta pasta guarda os segredos do ambiente de **desenvolvimento**. Nada daqui vai para o repositório,
só este leia-me. Em produção, os segredos são montados no contêiner em `/run/secrets/` (DDS §3.9).

| Arquivo | Conteúdo |
|---|---|
| `mysql_root` | Senha do root do MySQL de desenvolvimento |
| `sar_migracao` | Senha do usuário `sar_migracao` (migrações) |
| `sar_web`, `sar_worker`, `sar_expurgo` | Senhas dos usuários por processo (DD-58) |
| `chave_mestra` | Chave mestra da cifra, 32 bytes em base64 (DD-07) |

Para gerar todos de uma vez, com valores aleatórios:

```powershell
python scripts/criar_segredos_dev.py
```

O script não sobrescreve arquivo que já existe. A aplicação procura os segredos na pasta indicada por
`SAR_SEGREDOS` (padrão: `/run/secrets`).
