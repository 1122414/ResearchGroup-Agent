from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.services.cross_disciplinary_thesis_benchmark_service import (
    cross_disciplinary_thesis_benchmark_service,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="审计五种研究范式的真实完整硕士论文运行。")
    parser.add_argument(
        "--registry", type=Path,
        default=Path(__file__).parent / "benchmarks" / "thesis_projects.json",
    )
    args = parser.parse_args()
    result = cross_disciplinary_thesis_benchmark_service.run(args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
