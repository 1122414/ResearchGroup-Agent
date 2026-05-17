#!/usr/bin/env python3
"""Regression guardrails for frontend navigation smoothness changes.

This is intentionally dependency-free so it can run in local developer
environments without starting the frontend. It verifies the architectural
contracts that keep navigation responsive:

1. Run detail data is split into view-specific loaders.
2. Run detail polling is tiered instead of reloading every dataset at once.
3. Shared navigation resources use the request cache boundary.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_PAGE = ROOT / "frontend" / "src" / "app" / "runs" / "[run_id]" / "page.tsx"
API_FILE = ROOT / "frontend" / "src" / "lib" / "api.ts"
CACHE_FILE = ROOT / "frontend" / "src" / "lib" / "request-cache.ts"


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise AssertionError(message)


def main() -> int:
    run_page = RUN_PAGE.read_text(encoding="utf-8")
    api_file = API_FILE.read_text(encoding="utf-8")
    cache_file = CACHE_FILE.read_text(encoding="utf-8")

    print("[1/3] run detail split loading")
    for loader in [
        "refreshCore",
        "refreshOverview",
        "refreshWorkbench",
        "refreshEvidence",
        "refreshAudit",
    ]:
        require(run_page, loader, f"missing split loader: {loader}")
    if "api.getRun(runId)" in run_page:
        raise AssertionError("run detail should not issue the old extra getRun request on initial load")

    print("[2/3] tiered polling")
    require(run_page, "}, 2000)", "missing high-frequency lightweight polling")
    require(run_page, "}, 8000)", "missing low-frequency active-view polling")

    print("[3/3] shared request cache")
    require(cache_file, "class RequestCache", "missing request cache implementation")
    for snippet in [
        "getAgents: () => fetchCachedApi",
        "getRuns: () => fetchCachedApi",
        "getTasks: (runId?: string) =>",
        "getOutputs: (runId?: string) =>",
    ]:
        require(api_file, snippet, f"missing cached endpoint contract: {snippet}")

    print("OK - frontend navigation guardrails passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
