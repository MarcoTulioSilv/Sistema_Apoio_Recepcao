#!/usr/bin/env bash
# Cópia semanal para o pen drive da vez (DAS §7.4, item 3; RNF-504; DD-62), feita à mão pelo TI com o pen drive
# conectado. Copia os snapshots do repositório local para o repositório restic do pen drive, aplica a mesma retenção,
# confere e registra a execução no SAR (`sar job registrar copia_pendrive`). Sem cópia há mais de 8 dias, a pendência
# 17 aparece para o TI. Depois: desmontar, desconectar e levar o pen drive para fora da sala, com o registro do rodízio.
#
# Uso: sudo sar-copia-pendrive.sh /media/pendrive-a      (a pasta do pen drive montado)
set -Eeuo pipefail
umask 077

DESTINO_MONTADO=${1:?informe a pasta onde o pen drive está montado}
: "${RESTIC_REPOSITORY:?defina em /etc/sar/backup.env}"
: "${RESTIC_PASSWORD_FILE:?defina em /etc/sar/backup.env}"
: "${SAR_COMPOSE:?pasta do compose de produção}"
SAR_REGISTRAR=${SAR_REGISTRAR:-"docker compose --project-directory $SAR_COMPOSE exec -T worker sar"}
DESTINO="$DESTINO_MONTADO/sar-restic"

inicio=$(date --iso-8601=seconds)
registrar() {
  # shellcheck disable=SC2086 # SAR_REGISTRAR é um comando com argumentos
  $SAR_REGISTRAR job registrar copia_pendrive --resultado "$1" --inicio "$inicio" --fim "$(date --iso-8601=seconds)" \
    || echo "AVISO: o registro no SAR falhou; a cópia aparecerá como atrasada para o TI." >&2
}
trap 'echo "FALHA na linha $LINENO da cópia." >&2; registrar falha; exit 1' ERR

mountpoint -q "$DESTINO_MONTADO"  # nunca gravar no disco do próprio servidor por engano

# O repositório do pen drive usa a mesma senha (custódia dupla, RNF-622); na primeira vez, é criado.
if [ ! -f "$DESTINO/config" ]; then
  restic -r "$DESTINO" --password-file "$RESTIC_PASSWORD_FILE" init --copy-chunker-params \
    --from-repo "$RESTIC_REPOSITORY" --from-password-file "$RESTIC_PASSWORD_FILE"
fi
restic -r "$DESTINO" --password-file "$RESTIC_PASSWORD_FILE" copy \
  --from-repo "$RESTIC_REPOSITORY" --from-password-file "$RESTIC_PASSWORD_FILE"
restic -r "$DESTINO" --password-file "$RESTIC_PASSWORD_FILE" forget --keep-daily 30 --keep-weekly 12 \
  --keep-monthly 12 --prune
restic -r "$DESTINO" --password-file "$RESTIC_PASSWORD_FILE" check

trap - ERR
registrar sucesso
sync
echo "Cópia concluída. Desmonte o pen drive (umount $DESTINO_MONTADO) antes de desconectar."
