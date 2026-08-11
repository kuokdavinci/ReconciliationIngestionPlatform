#!/usr/bin/env bash
set -euo pipefail

if [[ ! "${AIRFLOW_DB_USER}" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "AIRFLOW_DB_USER must be a valid PostgreSQL role name" >&2
  exit 2
fi
if [[ ! "${AIRFLOW_DB_PASSWORD}" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo "AIRFLOW_DB_PASSWORD may only contain letters, numbers, '.', '_' and '-'" >&2
  exit 2
fi

role_exists=$(psql --host postgres --username postgres --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_roles WHERE rolname='${AIRFLOW_DB_USER}'")
if [[ "$role_exists" != "1" ]]; then
  psql --host postgres --username postgres --dbname postgres --set ON_ERROR_STOP=1 \
    --command "CREATE ROLE ${AIRFLOW_DB_USER} LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}'"
fi

database_exists=$(psql --host postgres --username postgres --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname='airflow'")
if [[ "$database_exists" != "1" ]]; then
  createdb --host postgres --username postgres --owner "${AIRFLOW_DB_USER}" airflow
fi
