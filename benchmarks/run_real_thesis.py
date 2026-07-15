from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from datetime import datetime, timezone

try:
    from benchmarks.run_live_e2e import DATASET as ENGINEERING_DATASET
    from benchmarks.run_live_e2e import request, validate_dataset
except ModuleNotFoundError:  # Direct script execution adds benchmarks/, not the repository root.
    from run_live_e2e import DATASET as ENGINEERING_DATASET
    from run_live_e2e import request, validate_dataset


WORLD_BANK_INDICATOR_URL = (
    "https://api.worldbank.org/v2/country/all/indicator/SE.XPD.TOTL.GD.ZS"
    "?date=2022&format=json&per_page=400"
)
WORLD_BANK_COUNTRIES_URL = "https://api.worldbank.org/v2/country?format=json&per_page=400"
WORLD_BANK_LICENSE_URL = "https://datacatalog.worldbank.org/public-licenses"
AUTO_APPROVALS = {"research_contract_freeze", "experiment_execute", "report_publish"}


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "ResearchGroup-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def build_social_dataset(indicator_payload: list, countries_payload: list) -> dict:
    countries = {
        item.get("id"): (item.get("incomeLevel") or {}).get("id")
        for item in countries_payload[1]
        if isinstance(item, dict) and item.get("id")
    }
    records = []
    for item in indicator_payload[1]:
        iso3 = item.get("countryiso3code")
        group = countries.get(iso3)
        value = item.get("value")
        if group not in {"HIC", "LMC"} or not iso3 or value is None:
            continue
        records.append({
            "country_code": iso3,
            "country": (item.get("country") or {}).get("value"),
            "year": item.get("date"),
            "income_group": group,
            "education_expenditure_gdp_pct": value,
        })
    if min(sum(item["income_group"] == group for item in records) for group in ("HIC", "LMC")) < 2:
        raise ValueError("World Bank snapshot has insufficient HIC/LMC observations")
    return {
        "title": "World Bank education expenditure snapshot by income group",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_urls": [WORLD_BANK_INDICATOR_URL, WORLD_BANK_COUNTRIES_URL],
        "indicator": "SE.XPD.TOTL.GD.ZS",
        "license": "CC BY 4.0; attribution and changes must be stated",
        "license_url": WORLD_BANK_LICENSE_URL,
        "method_data_package": {
            "schema_version": "research-method-data-v1",
            "family": "quantitative",
            "records": records,
            "outcome_field": "education_expenditure_gdp_pct",
            "group_field": "income_group",
            "baseline_group": "LMC",
            "treatment_group": "HIC",
            "measurement_definition": (
                "World Bank indicator SE.XPD.TOTL.GD.ZS: government expenditure on education, total (% of GDP)"
            ),
            "missing_data_policy": "Complete-case descriptive comparison; missing country-years are excluded and counted",
            "limitations": [
                "Cross-sectional aggregate comparison is descriptive and cannot identify a causal income effect",
                "2022 coverage is incomplete and group composition may confound the raw mean difference",
            ],
        },
    }


def _thesis_requirements(programme: str, target: int, minimum: int, maximum: int, source: str) -> dict:
    return {
        "degree_level": "master", "institution": "The University of Edinburgh",
        "programme": programme, "language": "en-GB", "citation_style": "Harvard",
        "minimum_word_count": minimum, "target_word_count": target, "maximum_word_count": maximum,
        "minimum_references": 5, "minimum_supported_claims": 5,
        "required_chapters": [
            "Introduction", "Literature Review", "Methodology", "Results", "Discussion", "Conclusion",
        ],
        "status": "confirmed", "requirements_source": source,
    }


def engineering_contract() -> dict:
    return {
        "research_type": "empirical",
        "primary_question": (
            "How do no-split, fixed non-overlapping, and fixed overlapping passage segmentation strategies compare "
            "on MRR and top-k accuracy in a frozen boundary-sensitive retrieval benchmark?"
        ),
        "objective": "Execute and independently reproduce a bounded passage-retrieval experiment without open-domain extrapolation.",
        "subquestions": [
            {"id": "sq1", "question": "What verified literature supports the retrieval metrics and segmentation choices?"},
            {"id": "sq2", "question": "What are the paired effects, uncertainty, and replication results?"},
        ],
        "scope_in": ["Frozen 40-document and 20-query benchmark", "Three preregistered segmentation strategies"],
        "scope_out": ["Generative answer quality", "Claims about open-domain corpora or production users"],
        "target_domain": "passage retrieval and document segmentation",
        "constraints": ["Standard-library deterministic evaluator", "At least three fixed seeds", "Hash all artifacts"],
        "expected_contribution": "A reproducible, boundary-sensitive comparison with explicit uncertainty and validity limits.",
        "novelty_criteria": ["Paired effect and independent reproduction rather than a single best score"],
        "data_availability": "The controlled benchmark, qrels, code, preregistration, and result hashes are stored in the run artifacts.",
        "ethics_risks": [],
        "success_criteria": ["All three strategies execute", "Artifact hashes and independent reproduction pass"],
        "failure_criteria": ["Missing qrels", "Reproduction outside tolerance", "Unsupported generalisation"],
        "discipline": {"broad_field": "engineering", "field": "computer_science", "subfield": "information_retrieval"},
        "methodology_profile": {
            "family": "computational", "epistemic_mode": "hypothesis_testing",
            "study_design": "controlled paired retrieval benchmark", "unit_of_analysis": "query",
            "evidence_types": ["verified full-text passages", "query-level retrieval records"],
            "data_collection_methods": ["deterministic execution over frozen user-supplied benchmark"],
            "analysis_methods": ["paired bootstrap", "ablation", "independent reproduction"],
            "quality_criteria": ["construct validity", "reproducibility", "bounded external validity"],
            "component_methods": [],
        },
        "resource_plan": [{
            "resource_type": "licensed_labeled_dataset", "description": "Frozen controlled benchmark with query/qrel labels",
            "required": True, "status": "available", "owner": "benchmark runner",
            "evidence": "Uploaded retrieval_benchmark.json with user_owned_for_research declaration",
            "resolution": "Keep the attachment and generated artifacts hash-frozen",
        }],
        "ethics_plan": {
            "required": False, "status": "not_required", "review_body": "", "approval_reference": "",
            "data_sensitivity": "No personal or participant data", "participant_risks": [],
        },
        "thesis_requirements": _thesis_requirements(
            "MSc Speech and Language Processing", 7500, 7000, 8000,
            "https://www.drps.ed.ac.uk/current/dpt/cxlasc11037.htm",
        ),
        "hypotheses": [{
            "statement": "Fixed overlapping segmentation improves MRR over the no-split baseline by at least 5%.",
            "rationale": "Boundary-spanning query terms are preregistered in the controlled benchmark.",
            "treatment": "fixed_100_overlap_30", "baseline": "no_split",
            "conditions": ["Frozen corpus, qrels, evaluator, and seeds"],
            "predicted_direction": "MRR increase", "primary_metric": "MRR",
            "minimum_effect": "relative improvement >= 5%",
            "falsification_criterion": "Relative improvement below 5% or paired interval includes zero",
        }],
    }


def social_contract() -> dict:
    return {
        "research_type": "empirical",
        "primary_question": (
            "In the frozen 2022 World Bank snapshot, how does reported government education expenditure as a "
            "percentage of GDP differ descriptively between high-income and lower-middle-income economies?"
        ),
        "objective": "Estimate a transparent aggregate mean difference and uncertainty without making a causal claim.",
        "subquestions": [
            {"id": "sq1", "question": "How should aggregate education expenditure comparisons be interpreted in prior research?"},
            {"id": "sq2", "question": "What difference and uncertainty appear in the frozen complete-case snapshot?"},
        ],
        "scope_in": ["World Bank 2022 indicator snapshot", "HIC and LMC economy classifications"],
        "scope_out": ["Individual outcomes", "Causal effects of income classification", "Imputation of missing values"],
        "target_domain": "comparative education policy and public expenditure",
        "constraints": ["Aggregate public data only", "Complete-case descriptive analysis", "No causal language"],
        "expected_contribution": "A reproducible descriptive comparison with an explicit missingness and ecological-inference boundary.",
        "novelty_criteria": ["Hash-frozen API snapshot and deterministic robustness statistic"],
        "data_availability": "World Bank API snapshot attached under CC BY 4.0 with source and retrieval time.",
        "ethics_risks": [],
        "success_criteria": ["At least two observations per group", "Effect, uncertainty, and median sensitivity recorded"],
        "failure_criteria": ["Insufficient group observations", "Missing provenance", "Causal overinterpretation"],
        "discipline": {"broad_field": "social_science", "field": "education_policy", "subfield": "public_expenditure"},
        "methodology_profile": {
            "family": "quantitative", "epistemic_mode": "estimation",
            "study_design": "cross-sectional aggregate observational comparison", "unit_of_analysis": "economy",
            "evidence_types": ["verified literature passages", "official aggregate indicator records"],
            "data_collection_methods": ["World Bank API snapshot with country metadata join"],
            "analysis_methods": ["complete-case group mean difference", "normal interval", "median sensitivity"],
            "quality_criteria": ["measurement validity", "missing-data disclosure", "uncertainty", "non-causal interpretation"],
            "component_methods": [],
        },
        "resource_plan": [{
            "resource_type": "open_aggregate_dataset", "description": "World Bank education expenditure and country metadata APIs",
            "required": True, "status": "available", "owner": "World Bank and benchmark runner",
            "evidence": f"{WORLD_BANK_INDICATOR_URL}; {WORLD_BANK_LICENSE_URL}; CC BY 4.0",
            "resolution": "Preserve API URLs, retrieval timestamp, attribution, and attachment hash",
        }],
        "ethics_plan": {
            "required": False, "status": "not_required", "review_body": "", "approval_reference": "",
            "data_sensitivity": "Public economy-level aggregate indicators; no human-level records", "participant_risks": [],
        },
        "thesis_requirements": _thesis_requirements(
            "MSc Social Research", 14000, 13000, 15000,
            "https://www.sps.ed.ac.uk/sites/default/files/assets/doc/PGT%20Dissertation/Taught%20MSc%20Student%20Dissertation%20Handbook%202025-26.pdf",
        ),
        "hypotheses": [{
            "statement": "The frozen HIC and LMC groups have a non-zero mean difference in reported education expenditure as a percentage of GDP.",
            "rationale": "This is an estimation target, not a causal income-effect hypothesis.",
            "treatment": "HIC classification", "baseline": "LMC classification",
            "conditions": ["Frozen 2022 complete-case World Bank snapshot"],
            "predicted_direction": "unspecified two-sided difference", "primary_metric": "raw mean difference in percentage points",
            "minimum_effect": "absolute mean difference > 0",
            "falsification_criterion": "No valid observations in either group or the estimated difference equals zero",
        }],
    }


def case_payload(case: str) -> tuple[str, dict, dict]:
    if case == "engineering":
        validate_dataset(ENGINEERING_DATASET)
        return "retrieval_benchmark.json", ENGINEERING_DATASET, engineering_contract()
    indicator = fetch_json(WORLD_BANK_INDICATOR_URL)
    countries = fetch_json(WORLD_BANK_COUNTRIES_URL)
    return "world_bank_education_2022.json", build_social_dataset(indicator, countries), social_contract()


def create_case(base_url: str, case: str) -> str:
    name, dataset, contract = case_payload(case)
    raw = json.dumps(dataset, ensure_ascii=False).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    goal = contract["primary_question"] + " Produce the complete dissertation only within the frozen contract and attached data."
    created = request(base_url, "POST", "/runs", {
        "research_goal": goal,
        "attachments": [{
            "name": name, "mime_type": "application/json", "size": len(raw),
            "data_url": "data:application/json;base64," + encoded,
        }],
    })
    run_id = created["run_id"]
    revised = request(base_url, "PATCH", f"/runs/{run_id}/research-contract", contract)
    if not revised.get("ready"):
        raise RuntimeError("contract rejected: " + json.dumps(revised.get("errors"), ensure_ascii=False))
    request(base_url, "POST", f"/runs/{run_id}/start", {})
    print(json.dumps({"event": "created", "case": case, "run_id": run_id}, ensure_ascii=False), flush=True)
    return run_id


def monitor(base_url: str, run_id: str, timeout: int) -> int:
    deadline = time.time() + timeout
    resolved: set[str] = set()
    last_status = ""
    while time.time() < deadline:
        snapshot = request(base_url, "GET", f"/runs/{run_id}")
        run = snapshot["run"]
        if run["status"] != last_status:
            print(json.dumps({"event": "status", "run_id": run_id, "status": run["status"], "step": run.get("current_step")}, ensure_ascii=False), flush=True)
            last_status = run["status"]
        if run["status"] in {"completed", "failed", "cancelled"}:
            return 0 if run["status"] == "completed" else 2
        if run["status"] == "waiting_confirmation":
            approvals = request(base_url, "GET", f"/runs/{run_id}/approvals")["items"]
            for item in [row for row in approvals if row["status"] == "pending"]:
                if item["id"] in resolved:
                    continue
                if item["request_type"] not in AUTO_APPROVALS:
                    print(json.dumps({"event": "blocked", "approval": item}, ensure_ascii=False), flush=True)
                    return 3
                request(
                    base_url, "POST", f"/runs/approvals/{item['id']}/resolve",
                    {"approved": True, "resolved_by": "stage11-real-thesis-runner"},
                )
                resolved.add(item["id"])
                print(json.dumps({"event": "approved", "type": item["request_type"]}, ensure_ascii=False), flush=True)
        time.sleep(2)
    print(json.dumps({"event": "timeout", "run_id": run_id}, ensure_ascii=False), flush=True)
    return 4


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real, contract-frozen master dissertation acceptance case.")
    parser.add_argument("--case", choices=["engineering", "social"], required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    run_id = args.run_id or create_case(args.base_url, args.case)
    return monitor(args.base_url, run_id, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
