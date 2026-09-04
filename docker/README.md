# Docker Services

## Các service Compose

`docker-compose.yml` hiện định nghĩa:

- `postgres`
- `mongodb`
- `sftp`
- `mongo-express`
- `api`
- `airflow-api-server`
- `airflow-scheduler`
- `airflow-dag-processor`
- `viettelpay-mock`

## Khởi động

```bash
docker compose up -d
```

Khởi động một nhóm service local nhỏ hơn:

```bash
docker compose up -d mongodb sftp mongo-express
```

`mongo-express` được cấu hình có chủ đích như một convenience service chỉ dùng
local. Compose hiện đặt `ME_CONFIG_BASICAUTH: "false"`, vì vậy hãy bind service
ở localhost và không coi thiết lập này là production default.

## Dừng

```bash
docker compose down
```

Xóa volume:

```bash
docker compose down -v
```

## MongoDB

- container: `reconciliation-mongo`
- exposed port: `27017`
- database: `reconciliation`
- init script: `docker/init-mongo.js`

Credential lấy từ `.env`:

- `MONGO_ROOT_USER`
- `MONGO_ROOT_PASSWORD`

## SFTP

- container: `reconciliation-sftp`
- exposed port: `2222`
- user/password from `.env`
- local folder `./sftp_data` is mounted to `/home/${SFTP_USER}/upload`

## API container

- container: `reconciliation-api`
- exposed port: `8000`
- startup command: `uvicorn src.api:create_app --factory --host 0.0.0.0 --port 8000`

## Ghi chú

- Airflow là workflow owner duy nhất. `airflow-scheduler` thực hiện DAG scheduling và task orchestration, không khởi động application scheduler thứ hai.
- `api` và `airflow-scheduler` nhận override `APP_MONGODB_URL` trỏ tới Compose MongoDB service.
- `airflow-scheduler` cũng override `SFTP_HOST=sftp`.
- `viettelpay-mock` dùng `Dockerfile.viettelpay-mock`, expose port `8001` và giữ state trong thư mục `mock_data` được mount.
- `mongo-express` chỉ dành cho local inspection, trừ khi được bổ sung auth và network restriction rõ ràng.
