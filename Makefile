.PHONY: test test-eval ci clean

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

# ── Clean ─────────────────────────────────────────────────────────
clean:
	rm -rf .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
