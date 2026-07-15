import argparse
import json
from pathlib import Path

from backend.app.services.research_benchmark_service import research_benchmark_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline research-integrity regression benchmarks.")
    parser.add_argument("--fixture", type=Path, default=Path("benchmarks/research_quality_cases.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = research_benchmark_service.run(args.fixture)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
