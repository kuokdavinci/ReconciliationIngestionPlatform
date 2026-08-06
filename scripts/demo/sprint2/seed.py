"""Reset the local, deterministic ViettelPay Sprint 2 mock contract fixture."""

import argparse
from pathlib import Path

from scripts.demo.sprint2.fixture import reset_viettelpay_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["reset"],
        help="Reset the local fixture; it does not mutate production databases.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("mock_data/viettelpay_sprint2"),
    )
    args = parser.parse_args()
    manifest = reset_viettelpay_fixture(args.output_dir)
    print(f"ViettelPay Sprint 2 fixture reset: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
