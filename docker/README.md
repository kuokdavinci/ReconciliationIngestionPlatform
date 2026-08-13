# Docker Services

## Compose Services

`docker-compose.yml` currently defines:

- `postgres`
- `mongodb`
- `sftp`
- `mongo-express`
- `api`
- `airflow-api-server`
- `airflow-scheduler`
- `airflow-dag-processor`
- `viettelpay-mock`

## Start

```bash
docker compose up -d
```

Bring up a smaller local set:

```bash
docker compose up -d mongodb sftp mongo-express
```

`mongo-express` is intentionally configured as a local-only convenience service.
The current Compose file sets `ME_CONFIG_BASICAUTH: "false"`, so keep it bound to localhost and do not treat that setting as a production default.

## Stop

```bash
docker compose down
```

Remove volumes:

```bash
docker compose down -v
```

## MongoDB

- container: `reconciliation-mongo`
- exposed port: `27017`
- database: `reconciliation`
- init script: `docker/init-mongo.js`

Credentials come from `.env`:

- `MONGO_ROOT_USER`
- `MONGO_ROOT_PASSWORD`

## SFTP

- container: `reconciliation-sftp`
- exposed port: `2222`
- user/password from `.env`
- local folder `./sftp_data` is mounted to `/home/${SFTP_USER}/upload`

## API Container

- container: `reconciliation-api`
- exposed port: `8000`
- startup command: `uvicorn src.api:create_app --factory --host 0.0.0.0 --port 8000`

## Notes

- Airflow is the only workflow owner. `airflow-scheduler` executes DAG scheduling and task orchestration; it does not start a second application scheduler.
- `api` and `airflow-scheduler` receive an `APP_MONGODB_URL` override pointing at the Compose MongoDB service.
- `airflow-scheduler` also overrides `SFTP_HOST=sftp`.
- `viettelpay-mock` uses `Dockerfile.viettelpay-mock`, exposes port `8001`, and keeps its state under the mounted `mock_data` directory.
- `mongo-express` is meant for local inspection only unless you add auth and network restrictions explicitly.
