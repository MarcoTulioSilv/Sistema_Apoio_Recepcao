#!/usr/bin/env bash
# Primeira inicialização do contêiner (DDS §12.3): o banco da aplicação (sar), o dos testes (sar_teste) e o
# usuário de migração nos dois. Os testes nunca tocam o banco da aplicação: cada rodada zera a trilha.
# Os usuários sar_web, sar_worker e sar_expurgo são criados depois, por `sar criar-usuarios-banco`, uma vez
# para cada banco (SAR_BANCO_NOME).
# No CI, roda fora do contêiner: SEGREDOS aponta a pasta e MYSQL_HOST/MYSQL_TCP_PORT, o servidor.
set -euo pipefail
SEGREDOS=${SEGREDOS:-/run/secrets}
senha=$(cat "$SEGREDOS/sar_migracao")
mysql -uroot -p"$(cat "$SEGREDOS/mysql_root")" <<SQL
CREATE USER IF NOT EXISTS 'sar_migracao'@'%' IDENTIFIED BY '${senha}';
CREATE DATABASE IF NOT EXISTS sar CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS sar_teste CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON sar.* TO 'sar_migracao'@'%';
GRANT ALL PRIVILEGES ON sar_teste.* TO 'sar_migracao'@'%';
SQL
