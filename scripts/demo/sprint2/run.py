"""Run the deterministic Sprint 2 recovery evaluation and write evidence."""

import argparse
import asyncio
from pathlib import Path

from scripts.demo.sprint2.evaluation import run_sprint2_evaluation


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Sprint 2 Incremental Recovery Evaluation",
        "",
        f"- Evidence type: `{report['evidenceType']}`",
        f"- Generated at: `{report['generatedAt']}`",
        f"- Summary: `{summary['passed']}/{summary['total']} passed`, `{summary['failed']} failed`",
        "",
        "| Scenario | Expected | Actual | Passed | Duration (ms) |",
        "|---|---|---|---:|---:|",
    ]
    for scenario in report["scenarios"]:
        lines.append(
            "| {id} — {name} | {expected} | {actual} | {passed} | {durationMs} |".format(
                **scenario
            )
        )
    lines.extend(
        [
            "",
            "## Final checkpoint",
            "",
            f"- Status: `{report['finalCheckpoint']['status']}`",
            f"- Last completed unit: `{report['finalCheckpoint']['lastCompletedUnitKey']}`",
            f"- Cursor after: `{report['finalCheckpoint']['cursorAfter']}`",
            f"- Duplicate ingestion keys: `{report['finalInvariant']['duplicateIngestionKeys']}`",
        ]
    )
    return "\n".join(lines) + "\n"


async def _run(output: Path) -> int:
    report = await run_sprint2_evaluation()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {output}")
    print(
        f"Sprint 2 evaluation: {report['summary']['passed']}/"
        f"{report['summary']['total']} passed"
    )
    return 0 if report["summary"]["failed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/phase-2/sprint-2-eval-run.md"),
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
