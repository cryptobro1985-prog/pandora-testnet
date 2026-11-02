#!/usr/bin/env bash
# Local development only: isolated PostgreSQL, never a production database.
set -euo pipefail
cd "$(dirname "$0")/.."
state=/workspace/.pandora-cloud
image=postgres@sha256:3b0cda93be7c8dba2ed484d19393d93845dc3dafb88973e248ba8e6d99d784e1
container=pandora-cloud-postgres
engine() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock "$@"
}
database() {
  mkdir -p "$state/pgdata"
  if engine container inspect "$container" >/dev/null 2>&1; then
    mount=$(engine inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' "$container")
    [ "$mount" = "$state/pgdata" ] || { echo 'Container name is in use by another database' >&2; exit 1; }
    engine start "$container" >/dev/null
  else
    engine run -d --name "$container" -p 127.0.0.1:55432:5432 \
      -e POSTGRES_USER=pandora -e POSTGRES_DB=pandora_dev -e POSTGRES_HOST_AUTH_METHOD=trust \
      --mount "type=bind,src=$state/pgdata,dst=/var/lib/postgresql/data" "$image" >/dev/null
  fi
  for attempt in {1..30}; do
    if engine exec "$container" pg_isready -U pandora >/dev/null; then break; fi
    sleep 1
  done
  engine exec "$container" pg_isready -U pandora
  if ! engine exec "$container" psql -U pandora -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='pandora_test'" | rg -q '^1$'; then
    engine exec "$container" createdb -U pandora pandora_test
  fi
}
case "${1:-help}" in
  install)
    python3.12 -m venv .venv
    .venv/bin/python -m pip install -r requirements-dev.txt
    .venv/bin/python -m pip check
    engine pull "$image"
    database
    ;;
  db) database ;;
  test)
    database
    umask 077
    printf '%s\n' 'postgresql://pandora@127.0.0.1:55432/pandora_test' > "$state/test-database-url"
    DATABASE_URL=postgresql://pandora@127.0.0.1:55432/pandora_test \
      PANDORA_TEST_DATABASE_URL_FILE="$state/test-database-url" \
      .venv/bin/python scripts/run_release_tests.py --report "${2:-$state/release-result.json}"
    ;;
  app)
    database
    export DATABASE_URL=postgresql://pandora@127.0.0.1:55432/pandora_dev
    export PANDORA_FLOW_V2=0 PANDORA_PUMP_V3=0
    export PORT=10000 RENDER_EXTERNAL_URL=http://127.0.0.1:10000
    exec .venv/bin/python app.py
    ;;
  *) echo 'Usage: bash scripts/cloud_dev.sh {install|db|test [report.json]|app}' ;;
esac
