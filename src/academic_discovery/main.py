from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from academic_discovery.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Academic job and fellowship discovery")
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from academic_discovery.pipeline import run_pipeline

    result = run_pipeline(load_config(args.config))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
