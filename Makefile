.PHONY: test test-eval ci clean \
	momo-e2e-run momo-e2e-job momo-e2e-rebuild \
	momo-e2e-phase2-file momo-e2e-help momo-e2e-reset momo-e2e-phase2 momo-e2e-phase2-full \
	momo-e2e-missing-partner-demo momo-sprint6-setup momo-sprint6-wave2 \
	zalopay-e2e-reset

# ── Test ──────────────────────────────────────────────────────────
test:
	uv run pytest tests/ --ignore=tests/test_analysis_e2e.py --ignore=tests/test_phase8.py -v

test-quick:
	uv run pytest tests/ --ignore=tests/test_analysis_e2e.py --ignore=tests/test_phase8.py -x --tb=short

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
	uv run pytest tests/ --ignore=tests/test_analysis_e2e.py --ignore=tests/test_phase8.py -v --tb=short

# ── MOMO E2E shortcuts ────────────────────────────────────────────
momo-e2e-reset:
	PYTHONPATH=. uv run python scripts/seeding/seed_momo_e2e.py reset --file-dir mock_data

momo-e2e-phase2:
	PYTHONPATH=. uv run python scripts/seeding/seed_momo_e2e.py phase2_duplicate --file-dir mock_data

momo-e2e-phase2-full:
	PYTHONPATH=. uv run python scripts/seeding/seed_momo_e2e.py phase2 --file-dir mock_data

momo-e2e-missing-partner-demo:
	PYTHONPATH=. uv run python scripts/seeding/seed_momo_e2e.py missing_partner_demo --file-dir mock_data

momo-sprint6-setup:
	PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py sprint6-setup

momo-sprint6-wave2:
	PYTHONPATH=. python scripts/seeding/seed_momo_e2e.py sprint6-wave2

momo-e2e-run:
	curl -s -X POST http://localhost:8000/api/v1/automation/jobs/MOMO/run | jq .

momo-e2e-job:
	curl -s http://localhost:8000/api/v1/automation/jobs | jq '.jobs[] | select(.partner == "MOMO")'

momo-e2e-rebuild:
	docker compose up -d --build api scheduler

momo-e2e-phase2-file:
	python -c 'import openpyxl, datetime; date_str = datetime.datetime.now().strftime("%Y-%m-%d"); wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sheet1"; [ws.append([]) for _ in range(6)]; headers = [""] * 30; headers[0], headers[1], headers[4], headers[7], headers[10], headers[17] = "STT", "msTransId", "msTotalAmount", "msNgayHoanThanh", "msMaHDon", "msTrangThaiGd"; ws.append(headers); [ws.append([(str(i + 1) if c == 0 else (f"MOMO_TXN_91{i:02d}" if c in (1, 10) else (str(100000 + i * 5000) if c == 4 else (f"{date_str} 12:00:00" if c == 7 else ("Thành công" if c == 17 else ""))))) for c in range(30)]) for i in range(20)]; filename = f"sftp_data/settlement_MOMO_{date_str.replace(\"-\", \"\")}.xlsx"; wb.save(filename); print(f"Generated Phase 2 Excel sheet: {filename}")'

# ── ZALOPAY E2E shortcuts ─────────────────────────────────────────
zalopay-e2e-reset:
	PYTHONPATH=. uv run python scripts/seeding/seed_zalopay_100k.py reset

momo-e2e-help:
	@echo "MOMO E2E — start here (2 main commands):"
	@echo "  make momo-e2e-reset               # clean Phase 1 (20 internal rows 9000-9019 + partner file)"
	@echo "  make momo-e2e-phase2              # partial duplicate demo (20 old + 10 new rows)"
	@echo "  make momo-e2e-phase2-full         # legacy full Wave 2 file (20 new rows)"
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
	@echo "  make momo-e2e-rebuild     # rebuild api + scheduler containers"

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
