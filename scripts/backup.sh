#!/usr/bin/env bash
# Backup cifrado incremental de los datos reales del despacho (casos,
# usuarios, firmas) a Backblaze B2, usando restic (single binary, cifra y
# deduplica solo — no hace falta armar tar+gpg a mano). Pensado para correr
# por cron en la VM (ver DEPLOY.md para la línea exacta de crontab).
#
# Variables de entorno requeridas (ponerlas en /root/.restic-env, ver
# DEPLOY.md — NO hardcodear acá ni subir ese archivo a git):
#   RESTIC_REPOSITORY   ej. b2:nombre-del-bucket:eoir-backup
#   RESTIC_PASSWORD     contraseña que cifra el backup (guardarla aparte,
#                        sin ella el backup es irrecuperable)
#   B2_ACCOUNT_ID / B2_ACCOUNT_KEY   credenciales de la application key de B2
#
# Uso manual: bash scripts/backup.sh
# Uso por cron: ver DEPLOY.md

set -euo pipefail

ENV_FILE="${RESTIC_ENV_FILE:-/root/.restic-env}"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "Faltan RESTIC_REPOSITORY/RESTIC_PASSWORD — revisa $ENV_FILE (ver DEPLOY.md)." >&2
  exit 1
fi

if ! command -v restic >/dev/null 2>&1; then
  echo "restic no está instalado — ver DEPLOY.md, sección de backups." >&2
  exit 1
fi

# Los volúmenes de Docker viven en /var/lib/docker/volumes/<proyecto>_<nombre>/_data
# — restic respalda esos directorios directo del disco, sin tocar los
# contenedores (no hace falta pararlos, son archivos JSON/PNG estáticos).
VOL_PREFIX="${VOL_PREFIX:-legal}"
DOCKER_VOLUMES_DIR="/var/lib/docker/volumes"

RUTAS=(
  "$DOCKER_VOLUMES_DIR/${VOL_PREFIX}_case_store_data/_data"
  "$DOCKER_VOLUMES_DIR/${VOL_PREFIX}_usuarios_data/_data"
  "$DOCKER_VOLUMES_DIR/${VOL_PREFIX}_firmas_data/_data"
)

# Inicializa el repositorio remoto la primera vez (no hace nada si ya existe).
restic snapshots >/dev/null 2>&1 || restic init

echo "Respaldando: ${RUTAS[*]}"
restic backup "${RUTAS[@]}" --tag eoir-diario

# Retención: 14 backups diarios, 8 semanales, 6 mensuales — suficiente para
# recuperar un error humano sin acumular espacio indefinidamente.
restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 6 --prune

echo "Backup completo: $(date -u +%FT%TZ)"
