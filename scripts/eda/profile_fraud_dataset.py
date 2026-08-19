"""Generate the current dataset's artifact through the generic profiler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eda.fraud_detection_dataset import (  # noqa: E402
    DEFAULT_INPUT,
    DEFAULT_OUTPUT_DIR,
    FRAUD_DATASET_SPEC,
)
from scripts.eda.profile_report import write_profile  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--distinct-limit", type=int, default=100_000)
    parser.add_argument("--prefix-rows", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    json_path, markdown_path = write_profile(
        args.input,
        args.output_dir,
        FRAUD_DATASET_SPEC,
        distinct_limit=args.distinct_limit,
        prefix_rows=args.prefix_rows,
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
