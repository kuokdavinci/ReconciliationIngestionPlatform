.PHONY: test test-integration test-eval ci clean \
	momo-e2e-run momo-e2e-job momo-e2e-rebuild momo-e2e-fail \
	momo-e2e-phase2-file momo-e2e-help momo-e2e-reset momo-e2e-phase2 momo-e2e-phase2-full \
	momo-e2e-missing-partner-demo momo-sprint6-setup momo-sprint6-wave2 \
	zalopay-e2e-reset viettelpay-sprint2-reset viettelpay-sprint2-phase2 viettelpay-sprint2-eval \
	vnpay-backfill-reset api-quick-build quarantine-demo-reset quarantine-demo-run quarantine-demo-fatal-run quarantine-demo-help

# ── Test ──────────────────────────────────────────────────────────
test:
	uv run pytest tests/ --ignore=tests/test_analysis_e2e.py -v

test-integration:
	uv run pytest tests/ --integration -m integration -v --tb=short

test-quick:
	uv run pytest tests/ --ignore=tests/test_analysis_e2e.py -x --tb=short

test-analysis:
	uv run pytest tests/test_analysis_*.py --ignore=tests/test_analysis_e2e.py -v

test-guardrails:
	uv run pytest tests/test_analysis_guardrails.py -v

# ── Eval — runs eval reference dataset through the pipeline ──────
test-eval:
	uv run pytest tests/test_analysis_scenarios.py -v -k "fallback or mixed_statuses"

eval-all:
	@echo "=== Eval: Running all analysis scenarios ==="
	uv run pytest tests/test_analysis_scenarios.py -v --ignore=tests/test_analysis_e2e.py
	@echo "=== Eval: Guardrail validation ==="
	uv run pytest tests/test_analysis_guardrails.py -v
	@echo "=== Eval: Provider fallback chain ==="
	uv run pytest tests/test_analysis_providers.py -v

# ── CI — runs everything except real LLM E2E tests ──────────────
ci:
	uv run pytest tests/ --integration --ignore=tests/test_analysis_e2e.py -v --tb=short

# ── MOMO E2E shortcuts ────────────────────────────────────────────
momo-e2e-reset:
	docker compose exec -T api env PYTHONPATH=/app python scripts/demo/sprint1/seed_momo_e2e.py reset --file-dir /app/mock_data

momo-e2e-fail:
	docker compose exec -T api env PYTHONPATH=/app python scripts/demo/sprint1/seed_momo_e2e.py fail --file-dir /app/mock_data

momo-e2e-phase2:
	docker compose exec -T api env PYTHONPATH=/app python scripts/demo/sprint1/seed_momo_e2e.py phase2_duplicate --file-dir /app/mock_data

momo-e2e-phase2-full:
	docker compose exec -T api env PYTHONPATH=/app python scripts/demo/sprint1/seed_momo_e2e.py phase2 --file-dir /app/mock_data

momo-e2e-missing-partner-demo:
	docker compose exec -T api env PYTHONPATH=/app python scripts/demo/sprint1/seed_momo_e2e.py missing_partner_demo --file-dir /app/mock_data

momo-sprint6-setup:
	PYTHONPATH=. python scripts/demo/sprint1/seed_momo_e2e.py sprint6-setup

momo-sprint6-wave2:
	PYTHONPATH=. python scripts/demo/sprint1/seed_momo_e2e.py sprint6-wave2

momo-e2e-run:
	curl -s -X POST http://localhost:8000/api/v1/automation/jobs/MOMO/run | jq .

momo-e2e-job:
	curl -s http://localhost:8000/api/v1/automation/jobs | jq '.jobs[] | select(.partner == "MOMO")'

momo-e2e-rebuild:
	docker compose up -d --build api airflow-api-server airflow-scheduler airflow-dag-processor

# ── Fast API image rebuild ───────────────────────────────────────
# Rebuild and recreate only the API container so UI checks use the current source image.
api-quick-build:
	docker compose up -d --build --force-recreate --no-deps api
	@docker inspect reconciliation-api --format='api image={{.Image}} created={{.Created}}'

momo-e2e-phase2-file:
	python -c 'import openpyxl, datetime; date_str = datetime.datetime.now().strftime("%Y-%m-%d"); wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sheet1"; [ws.append([]) for _ in range(6)]; headers = [""] * 30; headers[0], headers[1], headers[4], headers[7], headers[10], headers[17] = "STT", "msTransId", "msTotalAmount", "msNgayHoanThanh", "msMaHDon", "msTrangThaiGd"; ws.append(headers); [ws.append([(str(i + 1) if c == 0 else (f"MOMO_TXN_91{i:02d}" if c in (1, 10) else (str(100000 + i * 5000) if c == 4 else (f"{date_str} 12:00:00" if c == 7 else ("Thành công" if c == 17 else ""))))) for c in range(30)]) for i in range(20)]; filename = f"sftp_data/settlement_MOMO_{date_str.replace(\"-\", \"\")}.xlsx"; wb.save(filename); print(f"Generated Phase 2 Excel sheet: {filename}")'

# ── Sprint 2 — ViettelPay recovery demo ─────────────────────────
viettelpay-sprint2-reset:
	docker compose exec -T api python -m scripts.demo.sprint2.seed reset
	docker compose up -d viettelpay-mock

viettelpay-sprint2-phase2:
	docker compose up -d viettelpay-mock
	docker compose exec -T viettelpay-mock python -m scripts.demo.sprint2.mock_api --phase2 --state-file /app/mock_data/viettelpay_sprint2/mock_api_state.json

viettelpay-sprint2-eval:
	PYTHONPATH=. uv run python -m scripts.demo.sprint2.run

vnpay-backfill-reset:
	docker compose exec -T api env PYTHONPATH=/app VNPAY_BACKFILL_FROM="$${VNPAY_BACKFILL_FROM:-}" VNPAY_BACKFILL_TO="$${VNPAY_BACKFILL_TO:-}" python -m scripts.demo.sprint2.seed_vnpay_filedrop_backfill reset

# ── Quarantine operator UI demo ─────────────────────────────────
quarantine-demo-reset:
	docker compose exec -T api env PYTHONPATH=/app python -m scripts.demo.scenarios.seed_quarantine_demo reset

quarantine-demo-run:
	docker compose exec -T api python -c 'import json, urllib.request; request = urllib.request.Request("http://127.0.0.1:8000/api/v1/automation/jobs/DEMO/run", method="POST", headers={"X-Actor": "demo-operator"}); print(json.dumps(json.load(urllib.request.urlopen(request)), indent=2))'

quarantine-demo-fatal-run:
	docker compose exec -T api python -c 'import json, urllib.request; request = urllib.request.Request("http://127.0.0.1:8000/api/v1/automation/jobs/DEMO1/run", method="POST", headers={"X-Actor": "demo-operator"}); print(json.dumps(json.load(urllib.request.urlopen(request)), indent=2))'

quarantine-demo-help:
	@echo "Quarantine demo: run 'make quarantine-demo-reset' after the local Compose API is healthy."
	@echo "Then run 'make quarantine-demo-run' for the DEMO scheduler-first flow."
	@echo "Open Review Center → Review Packets, approve the DEMO mapping packet, then review the conflict duplicate and missing-amount row in Quarantine."
	@echo "Run 'make quarantine-demo-fatal-run' to execute DEMO1 directly and see BATCH_FATAL in Schedules."

# ── ZALOPAY E2E shortcuts ─────────────────────────────────────────
zalopay-e2e-reset:
	PYTHONPATH=. uv run python scripts/seeding/seed_zalopay_100k.py reset

momo-e2e-help:
	@echo "MOMO E2E — main modes:"
	@echo "  make momo-e2e-reset               # clean Phase 1 (20 internal rows 9000-9019 + partner file)"
	@echo "  make momo-e2e-fail                # Docker-native fixture; missing id/trace; next Run Now must show FAILED"
	@echo "  make momo-e2e-phase2              # partial duplicate/review demo (20 old + 10 new rows, new delivery)"
	@echo "  make momo-e2e-phase2-full         # standard happy path Wave 2 file (20 new rows, approved mapping reused)"
	@echo ""
	@echo "Optional:"
	@echo "  make momo-e2e-missing-partner-demo  # inject MOMO_TXN_90_MISSING_PARTNER for engine demo"
	@echo "  make momo-sprint6-setup             # full MOMO cleanup + Sprint 6 dataset (20 internal wave1, wave2 hold)"
	@echo "  make momo-sprint6-wave2             # activate Sprint 6 wave 2 file"
	@echo ""
	@echo "Inspection / ops:"
	@echo "  make momo-e2e-run         # trigger MOMO automation run"
	@echo "  make momo-e2e-job         # inspect MOMO automation job"
	@echo "  make momo-e2e-phase2-file # write Wave 2 partner file (9100-9119) only"
	@echo "  make momo-e2e-rebuild     # rebuild api + Airflow containers"

# ── Frontend (Next.js) ────────────────────────────────────────────
.PHONY: frontend-dev frontend-build

frontend-dev:
	cd frontend-next && npm run dev

frontend-build:
	cd frontend-next && npm run build

# ── Clean ─────────────────────────────────────────────────────────
clean:
	rm -rf .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
