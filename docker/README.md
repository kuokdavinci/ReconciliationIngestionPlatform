# Docker Services

## Compose Services

`docker-compose.yml` currently defines:

- `mongodb`
- `sftp`
- `mongo-express`
- `api`
- `scheduler`

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

## Scheduler Container

- container: `reconciliation-scheduler`
- startup command: `python run.py --start-scheduler`

## Notes

- `api` and `scheduler` both receive an `APP_MONGODB_URL` override pointing at the Compose MongoDB service.
- `scheduler` also overrides `SFTP_HOST=sftp`.
- `mongo-express` is meant for local inspection only unless you add auth and network restrictions explicitly.
