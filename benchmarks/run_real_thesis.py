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

ENGINEERING_SEED_SOURCES = [
    {
        "title": "Document Segmentation Matters for Retrieval-Augmented Generation",
        "year": 2025, "venue": "Findings of ACL", "doi": "10.18653/v1/2025.findings-acl.422",
        "url": "https://aclanthology.org/2025.findings-acl.422/",
    },
    {
        "title": "Dense Passage Retrieval for Open-Domain Question Answering",
        "year": 2020, "venue": "EMNLP", "doi": "10.18653/v1/2020.emnlp-main.550",
        "url": "https://aclanthology.org/2020.emnlp-main.550/",
    },
    {
        "title": "Grounding Language Model with Chunking-Free In-Context Retrieval",
        "year": 2024, "venue": "ACL", "doi": "10.18653/v1/2024.acl-long.71",
        "url": "https://aclanthology.org/2024.acl-long.71/",
    },
    {
        "title": "Question-Based Retrieval using Atomic Units for Enterprise RAG",
        "year": 2024, "venue": "FEVER", "doi": "10.18653/v1/2024.fever-1.25",
        "url": "https://aclanthology.org/2024.fever-1.25/",
    },
    {
        "title": "RAGAS: Automated Evaluation of Retrieval Augmented Generation",
        "year": 2024, "venue": "EACL System Demonstrations", "doi": "10.18653/v1/2024.eacl-demo.16",
        "url": "https://aclanthology.org/2024.eacl-demo.16/",
    },
    {
        "title": "Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models",
        "year": 2024, "venue": "arXiv", "url": "https://arxiv.org/abs/2409.04701",
    },
]

SOCIAL_SEED_SOURCES = [
    {
        "title": "Education Finance Watch 2024",
        "authors": "World Bank; UNESCO", "year": 2024, "venue": "World Bank",
        "url": "https://documents1.worldbank.org/curated/en/099102824144527868/pdf/P50097819250a00ce1812018168df2deaa3.pdf",
        "source_type": "report",
    },
    {
        "title": "Education Finance Watch 2023",
        "authors": "World Bank; UNESCO", "year": 2023, "venue": "World Bank",
        "url": "https://documents1.worldbank.org/curated/en/099103123163755271/pdf/P17813506cd84f07a0b6be0c6ea576d59f8.pdf",
        "source_type": "report",
    },
    {
        "title": "Education Finance Watch 2021",
        "authors": "World Bank; UNESCO", "year": 2021, "venue": "World Bank",
        "url": "https://documents1.worldbank.org/curated/en/226481614027788096/pdf/Education-Finance-Watch-2021.pdf",
        "source_type": "report",
    },
    {
        "title": "The Impact of Government Expenditure on Education in the ESG Models at World Level",
        "authors": "Angelo Leogrande; Alberto Costantiello", "year": 2023,
        "venue": "Munich Personal RePEc Archive", "doi": "10.31235/osf.io/4wctx",
        "url": "https://mpra.ub.uni-muenchen.de/117216/1/04-05-2023%20GEE%20and%20ESG.pdf",
        "source_type": "paper",
    },
    {
        "title": "Impact of Government Expenditure on Education and GDP",
        "authors": "Shom Bhattarai", "year": 2024, "venue": "Journal of Gurubaba",
        "doi": "10.3126/jg.v6i2.82443",
        "url": "https://www.nepjol.info/index.php/jg/article/download/82443/63056",
        "source_type": "paper",
    },
    {
        "title": "Government spending on education as a share of GDP",
        "authors": "Our World in Data; UNESCO Institute for Statistics", "year": 2026,
        "venue": "Our World in Data", "url": "https://ourworldindata.org/grapher/education-spending",
        "source_type": "dataset",
    },
]

PUBLIC_TEXT_SOURCES = {
    "humanities": [
        {
            "name": "wollstonecraft_vindication_excerpt.txt",
            "title": "A Vindication of the Rights of Woman",
            "authors": "Mary Wollstonecraft",
            "url": "https://www.gutenberg.org/cache/epub/3420/pg3420.txt",
            "markers": ["A VINDICATION OF THE RIGHTS OF WOMAN", "MARY WOLLSTONECRAFT"],
        },
        {
            "name": "burke_reflections_excerpt.txt",
            "title": "Reflections on the Revolution in France",
            "authors": "Edmund Burke",
            "url": "https://www.gutenberg.org/cache/epub/15679/pg15679.txt",
            "markers": ["REFLECTIONS ON THE REVOLUTION IN FRANCE", "EDMUND BURKE"],
        },
    ],
    "qualitative": [
        {
            "name": "douglass_narrative_excerpt.txt",
            "title": "Narrative of the Life of Frederick Douglass",
            "authors": "Frederick Douglass",
            "url": "https://www.gutenberg.org/cache/epub/23/pg23.txt",
            "markers": ["NARRATIVE OF THE LIFE OF FREDERICK DOUGLASS", "FREDERICK DOUGLASS"],
        },
        {
            "name": "jacobs_incidents_excerpt.txt",
            "title": "Incidents in the Life of a Slave Girl",
            "authors": "Harriet A. Jacobs",
            "url": "https://www.gutenberg.org/cache/epub/11030/pg11030.txt",
            "markers": ["INCIDENTS IN THE LIFE OF A SLAVE GIRL", "HARRIET A. JACOBS"],
        },
    ],
}
GUTENBERG_LICENSE = "Public domain in the USA; Project Gutenberg terms apply to the electronic edition"


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "ResearchGroup-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ResearchGroup-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def build_public_text_corpus(case: str, downloaded: dict[str, str] | None = None) -> list[dict]:
    records = []
    for source in PUBLIC_TEXT_SOURCES[case]:
        text = (downloaded or {}).get(source["url"]) if downloaded is not None else fetch_text(source["url"])
        if not text or not all(marker.casefold() in text.casefold() for marker in source["markers"]):
            raise ValueError(f"Downloaded public text failed identity check: {source['url']}")
        start_marker = "*** START OF"
        start = text.upper().find(start_marker)
        body = text[text.find("\n", start) + 1:] if start >= 0 else text
        excerpt = body.strip()[:10000]
        content = (
            f"Source title: {source['title']}\nAuthor: {source['authors']}\n"
            f"Source URL: {source['url']}\nExtraction: first 10,000 characters after the Gutenberg start marker\n\n"
            f"{excerpt}"
        )
        records.append({
            **source, "mime_type": "text/plain", "content": content,
            "source_url": source["url"], "license": GUTENBERG_LICENSE, "provenance": source["url"],
        })
    return records


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


def systematic_review_contract() -> dict:
    return {
        "research_type": "survey",
        "primary_question": (
            "Across a frozen pool of verified full-text studies, what effects, evaluation choices, and limitations "
            "are reported for passage segmentation in retrieval-augmented generation?"
        ),
        "objective": "Conduct a reproducible bounded systematic review with independent dual screening and appraisal.",
        "subquestions": [
            {"id": "sq1", "question": "Which verified studies satisfy the frozen inclusion criteria?"},
            {"id": "sq2", "question": "What findings and validity limitations recur across included studies?"},
        ],
        "scope_in": ["English full-text empirical studies in the frozen seed/search pool", "Passage segmentation and retrieval evaluation"],
        "scope_out": ["Unverified citations", "Generation quality without retrieval evaluation", "Meta-analysis of incompatible outcomes"],
        "target_domain": "systematic evidence synthesis of RAG passage segmentation",
        "constraints": ["Dual full-text screening", "No study without verified passage evidence", "Narrative synthesis when outcomes differ"],
        "expected_contribution": "A traceable synthesis separating reported findings from cross-study inference.",
        "novelty_criteria": ["Hash-frozen evidence pool with independent screening records"],
        "data_availability": "Protocol attachment, verified passages, screening records, and appraisal artifacts remain in the run directory.",
        "ethics_risks": [],
        "success_criteria": ["Every frozen study is screened twice", "Every included study is appraised", "Disagreements are disclosed"],
        "failure_criteria": ["A study is skipped", "Metadata-only evidence supports a finding", "Screening is single-reviewer"],
        "discipline": {"broad_field": "information_science", "field": "evidence_synthesis", "subfield": "retrieval_augmented_generation"},
        "methodology_profile": {
            "family": "systematic_review", "epistemic_mode": "evidence_synthesis",
            "study_design": "bounded systematic review", "unit_of_analysis": "verified full-text study",
            "evidence_types": ["verified full-text passages", "screening and appraisal records"],
            "data_collection_methods": ["seeded scholarly retrieval", "deduplication", "independent dual screening"],
            "analysis_methods": ["quality appraisal", "structured narrative synthesis"],
            "quality_criteria": ["study identity", "screening completeness", "appraisal coverage", "flow accounting"],
            "component_methods": [],
        },
        "resource_plan": [{
            "resource_type": "verified_fulltext_study_pool", "description": "Five traceable open scholarly records plus provider search",
            "required": True, "status": "available", "owner": "benchmark runner and evidence pipeline",
            "evidence": "Seed URLs/DOIs and full-text passage hashes stored in the run",
            "resolution": "Fail if verified full text is unavailable",
        }],
        "ethics_plan": {
            "required": False, "status": "not_required", "review_body": "", "approval_reference": "",
            "data_sensitivity": "Published scholarly literature only", "participant_risks": [],
        },
        "thesis_requirements": _thesis_requirements(
            "MSc Speech and Language Processing", 7500, 7000, 8000,
            "https://www.drps.ed.ac.uk/current/dpt/cxlasc11037.htm",
        ),
        "hypotheses": [],
    }


def _public_text_contract(case: str) -> dict:
    humanities = case == "humanities"
    return {
        "research_type": "interpretive",
        "primary_question": (
            "How do the frozen opening excerpts of Wollstonecraft's Vindication and Burke's Reflections construct "
            "authority, reason, and political change?" if humanities else
            "How do the frozen opening excerpts of Douglass's Narrative and Jacobs's Incidents construct agency, "
            "constraint, and counterexamples to dominant accounts of enslavement?"
        ),
        "objective": (
            "Produce a source-critical comparative interpretation bounded to two public-domain primary-text excerpts."
            if humanities else
            "Conduct a transparent qualitative coding comparison of two public-domain autobiographical excerpts."
        ),
        "subquestions": [
            {"id": "sq1", "question": "What recurring concepts are grounded in each frozen excerpt?"},
            {"id": "sq2", "question": "Which counterexamples or alternative readings limit the comparison?"},
        ],
        "scope_in": ["First 10,000 post-header characters of each hash-frozen Project Gutenberg text", "Comparative close reading" if humanities else "Qualitative thematic coding"],
        "scope_out": ["Claims about each complete book", "Claims about authorial intention not grounded in the excerpts", "Population generalisation"],
        "target_domain": "comparative political rhetoric" if humanities else "qualitative analysis of public-domain autobiographical narratives",
        "constraints": ["Two independently sourced texts", "Stable segment/source IDs", "Negative or counter-reading required"],
        "expected_contribution": "A bounded, reproducible comparison with explicit interpretive alternatives.",
        "novelty_criteria": ["Hash-linked source-to-interpretation audit trail"],
        "data_availability": "Downloaded public-domain sources, extraction boundaries, URLs, and hashes are stored with the run.",
        "ethics_risks": [],
        "success_criteria": ["All interpretations trace to supplied sources", "Independent review covers every analyzed unit"],
        "failure_criteria": ["Unknown source IDs", "Unreviewed coding or interpretation", "Whole-book overgeneralisation"],
        "discipline": {
            "broad_field": "humanities" if humanities else "social_science",
            "field": "intellectual_history" if humanities else "qualitative_historical_sociology",
            "subfield": "political_rhetoric" if humanities else "narrative_agency",
        },
        "methodology_profile": {
            "family": "humanities" if humanities else "qualitative", "epistemic_mode": "interpretation",
            "study_design": "comparative source-critical close reading" if humanities else "comparative qualitative document analysis",
            "unit_of_analysis": "primary-text excerpt" if humanities else "hashed text segment",
            "evidence_types": ["public-domain primary text", "verified scholarship passages"],
            "data_collection_methods": ["identity-checked Project Gutenberg download", "deterministic bounded extraction"],
            "analysis_methods": ["source criticism", "contextual interpretation", "counter-reading"] if humanities else
            ["codebook development", "segment coding", "negative-case analysis"],
            "quality_criteria": ["source traceability", "triangulation", "independent interpretive review"] if humanities else
            ["codebook coverage", "audit trail", "negative cases", "independent coding review"],
            "component_methods": [],
        },
        "resource_plan": [{
            "resource_type": "public_domain_primary_texts", "description": "Two identity-checked Project Gutenberg editions",
            "required": True, "status": "available", "owner": "Project Gutenberg and benchmark runner",
            "evidence": GUTENBERG_LICENSE + "; " + "; ".join(item["url"] for item in PUBLIC_TEXT_SOURCES[case]),
            "resolution": "Fail download if title/author markers do not match",
        }],
        "ethics_plan": {
            "required": False, "status": "not_required", "review_body": "", "approval_reference": "",
            "data_sensitivity": "Public-domain historical texts; no recruited participants or private records", "participant_risks": [],
        },
        "thesis_requirements": _thesis_requirements(
            "MSc Social Research", 14000, 13000, 15000,
            "https://www.sps.ed.ac.uk/sites/default/files/assets/doc/PGT%20Dissertation/Taught%20MSc%20Student%20Dissertation%20Handbook%202025-26.pdf",
        ),
        "hypotheses": [],
    }


def humanities_contract() -> dict:
    return _public_text_contract("humanities")


def qualitative_contract() -> dict:
    return _public_text_contract("qualitative")


def case_payload(case: str) -> tuple[list[dict], dict, list[dict]]:
    if case == "engineering":
        validate_dataset(ENGINEERING_DATASET)
        return [{
            "name": "retrieval_benchmark.json", "mime_type": "application/json",
            "content": json.dumps(ENGINEERING_DATASET, ensure_ascii=False),
            "provenance": "user_owned_for_research frozen benchmark",
        }], engineering_contract(), ENGINEERING_SEED_SOURCES
    if case == "social":
        indicator = fetch_json(WORLD_BANK_INDICATOR_URL)
        countries = fetch_json(WORLD_BANK_COUNTRIES_URL)
        dataset = build_social_dataset(indicator, countries)
        return [{
            "name": "world_bank_education_2022.json", "mime_type": "application/json",
            "content": json.dumps(dataset, ensure_ascii=False), "source_url": WORLD_BANK_INDICATOR_URL,
            "license": dataset["license"], "provenance": WORLD_BANK_INDICATOR_URL,
        }], social_contract(), SOCIAL_SEED_SOURCES
    if case == "systematic":
        protocol = {
            "schema_version": "systematic-review-protocol-v1",
            "inclusion": ["verified full text", "reports passage segmentation and retrieval evaluation"],
            "exclusion": ["metadata only", "no retrieval evaluation"],
            "screening": "two independent full-text decisions; disagreements excluded and disclosed",
        }
        return [{
            "name": "systematic_review_protocol.json", "mime_type": "application/json",
            "content": json.dumps(protocol, ensure_ascii=False), "provenance": "benchmark preregistration",
        }], systematic_review_contract(), ENGINEERING_SEED_SOURCES
    records = build_public_text_corpus(case)
    contract = humanities_contract() if case == "humanities" else qualitative_contract()
    seeds = [
        {key: item[key] for key in ("title", "authors", "url")} | {
            "venue": "Project Gutenberg", "source_type": "primary_source",
        }
        for item in PUBLIC_TEXT_SOURCES[case]
    ]
    return records, contract, seeds


def create_case(base_url: str, case: str) -> str:
    records, contract, seeds = case_payload(case)
    attachments = []
    for record in records:
        raw = record.pop("content").encode("utf-8")
        attachments.append({
            **record, "size": len(raw),
            "data_url": f"data:{record['mime_type']};base64," + base64.b64encode(raw).decode("ascii"),
        })
    goal = contract["primary_question"] + " Produce the complete dissertation only within the frozen contract and attached data."
    created = request(base_url, "POST", "/runs", {
        "research_goal": goal,
        "seed_sources": seeds,
        "attachments": attachments,
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
    parser.add_argument(
        "--case", choices=["engineering", "social", "systematic", "humanities", "qualitative"], required=True,
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    run_id = args.run_id or create_case(args.base_url, args.case)
    return monitor(args.base_url, run_id, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
