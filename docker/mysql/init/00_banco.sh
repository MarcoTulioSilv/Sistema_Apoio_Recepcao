#!/usr/bin/env bash
# Primeira inicialização do contêiner: banco sar e usuário de migração (DDS §12.3).
# Os usuários sar_web, sar_worker e sar_expurgo são criados depois, por `sar criar-usuarios-banco`.
# No CI, roda fora do contêiner: SEGREDOS aponta a pasta e MYSQL_HOST/MYSQL_TCP_PORT, o servidor.
set -euo pipefail
SEGREDOS=${SEGREDOS:-/run/secrets}
senha=$(cat "$SEGREDOS/sar_migracao")
mysql -uroot -p"$(cat "$SEGREDOS/mysql_root")" <<SQL
CREATE DATABASE IF NOT EXISTS sar CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'sar_migracao'@'%' IDENTIFIED BY '${senha}';
GRANT ALL PRIVILEGES ON sar.* TO 'sar_migracao'@'%';
SQL
