#!/usr/bin/env bash
# Backup diário do servidor (DAS §7.4, DD-62, AD-25), pelo agendamento do sistema operacional (sar-backup.timer, 02:20,
# depois da âncora das 02:00). Faz o dump consistente do SAR e do SCE, o snapshot restic cifrado no HD local separado
# e a retenção; ao fim, registra a execução no SAR (`sar job registrar backup`), com sucesso ou falha. Backup atrasado
# ou com falha vira a pendência 17 do TI.
#
# Configuração em /etc/sar/backup.env (modelo: backup.env.exemplo), legível só pelo root. A senha do restic fica num
# arquivo próprio, em custódia dupla com o TI e a administração (RNF-622). Nenhum dado de paciente vai para a saída:
# só caminhos e contagens.
set -Eeuo pipefail
umask 077

: "${RESTIC_REPOSITORY:?defina em /etc/sar/backup.env}"
: "${RESTIC_PASSWORD_FILE:?defina em /etc/sar/backup.env}"
: "${SAR_COMPOSE:?pasta do compose de produção}"
: "${SAR_COFRE_HOST:?pasta do cofre no servidor}"
: "${SAR_DUMPS:?pasta temporária dos dumps, no HD do backup}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
SAR_CADDY_DADOS=${SAR_CADDY_DADOS:-}
SAR_CONFIGURACAO=${SAR_CONFIGURACAO:-/etc/sar}
SAR_REGISTRAR=${SAR_REGISTRAR:-"docker compose --project-directory $SAR_COMPOSE exec -T worker sar"}
SERVICO_MYSQL_SAR=${SERVICO_MYSQL_SAR:-mysql}
SERVICO_MYSQL_SCE=${SERVICO_MYSQL_SCE:-}   # vazio: o SCE ainda não está neste servidor
BANCO_SCE=${BANCO_SCE:-sce}

inicio=$(date --iso-8601=seconds)

registrar() {  # resultado
  # shellcheck disable=SC2086 # SAR_REGISTRAR é um comando com argumentos
  $SAR_REGISTRAR job registrar backup --resultado "$1" --inicio "$inicio" --fim "$(date --iso-8601=seconds)" \
    || echo "AVISO: o registro no SAR falhou; o backup aparecerá como atrasado para o TI." >&2
}
falhou() {
  echo "FALHA na linha $1 do backup." >&2
  registrar falha
  exit 1
}
trap 'falhou $LINENO' ERR

dump() {  # serviço do compose, banco, arquivo de saída
  docker compose --project-directory "$SAR_COMPOSE" exec -T "$1" sh -c \
    'exec mysqldump -uroot -p"$(cat /run/secrets/mysql_root)" --single-transaction --routines --triggers \
       --hex-blob --databases "$0"' "$2" > "$3"
  test -s "$3"
}

mkdir -p "$SAR_DUMPS"
rm -f "$SAR_DUMPS"/*.sql
dump "$SERVICO_MYSQL_SAR" sar "$SAR_DUMPS/sar.sql"
if [ -n "$SERVICO_MYSQL_SCE" ]; then
  dump "$SERVICO_MYSQL_SCE" "$BANCO_SCE" "$SAR_DUMPS/sce.sql"
fi

# A quarentena nunca entra (SEG-29): ela fica fora da pasta do cofre, e o exclude garante.
fontes=("$SAR_DUMPS" "$SAR_COFRE_HOST" "$SAR_CONFIGURACAO")
if [ -n "$SAR_CADDY_DADOS" ]; then fontes+=("$SAR_CADDY_DADOS"); fi
restic backup --tag diario --exclude '*/quarentena' --exclude '*/quarentena/*' "${fontes[@]}"

# Retenção (DAS §7.4, item 5): é o horizonte em que um documento descartado deixa de existir no backup (DD-04).
restic forget --tag diario --keep-daily 30 --keep-weekly 12 --keep-monthly 12 --prune

# Integridade do repositório (item 4): aos domingos, lendo uma amostra dos dados.
if [ "$(date +%u)" = "7" ]; then
  restic check --read-data-subset=5%
fi

rm -f "$SAR_DUMPS"/*.sql  # já estão no snapshot cifrado
trap - ERR
registrar sucesso
echo "Backup concluído."
