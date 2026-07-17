import base64
import json

import pytest

from benchmarks.run_real_thesis import (
    ENGINEERING_SEED_SOURCES,
    SOCIAL_SEED_SOURCES,
    PUBLIC_TEXT_SOURCES,
    build_public_text_corpus,
    build_social_dataset,
    engineering_contract,
    humanities_contract,
    qualitative_contract,
    social_contract,
    systematic_review_contract,
)
from backend.app.services.research_contract_service import research_contract_service
from backend.app.api.routes_runs import _persist_attachment_sources, _save_and_extract_attachments
from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.storage.repositories import EvidenceRepository, FullTextDocumentRepository


def test_real_thesis_contracts_freeze_actual_programme_limits():
    engineering = engineering_contract()["thesis_requirements"]
    social = social_contract()["thesis_requirements"]

    assert engineering["maximum_word_count"] == 8000
    assert "drps.ed.ac.uk" in engineering["requirements_source"]
    assert social["maximum_word_count"] == 15000
    assert "sps.ed.ac.uk" in social["requirements_source"]
    assert systematic_review_contract()["methodology_profile"]["family"] == "systematic_review"
    assert humanities_contract()["methodology_profile"]["family"] == "humanities"
    assert qualitative_contract()["methodology_profile"]["family"] == "qualitative"


@pytest.mark.parametrize(
    "contract_factory",
    [engineering_contract, social_contract, systematic_review_contract, humanities_contract, qualitative_contract],
)
def test_every_real_thesis_contract_passes_the_same_runtime_validator(contract_factory):
    contract = contract_factory()

    assert research_contract_service.validate(contract, contract["hypotheses"]) == []


def test_world_bank_payload_is_joined_without_fabricating_missing_values():
    indicators = [{}, [
        {"countryiso3code": "AAA", "country": {"value": "A"}, "date": "2022", "value": 5.0},
        {"countryiso3code": "AAB", "country": {"value": "B"}, "date": "2022", "value": 6.0},
        {"countryiso3code": "BBB", "country": {"value": "C"}, "date": "2022", "value": 3.0},
        {"countryiso3code": "BBC", "country": {"value": "D"}, "date": "2022", "value": 4.0},
        {"countryiso3code": "MISS", "country": {"value": "Missing"}, "date": "2022", "value": None},
    ]]
    countries = [{}, [
        {"id": "AAA", "incomeLevel": {"id": "HIC"}},
        {"id": "AAB", "incomeLevel": {"id": "HIC"}},
        {"id": "BBB", "incomeLevel": {"id": "LMC"}},
        {"id": "BBC", "incomeLevel": {"id": "LMC"}},
        {"id": "MISS", "incomeLevel": {"id": "LMC"}},
    ]]

    result = build_social_dataset(indicators, countries)
    records = result["method_data_package"]["records"]

    assert len(records) == 4
    assert {item["income_group"] for item in records} == {"HIC", "LMC"}
    assert result["license"] == "CC BY 4.0; attribution and changes must be stated"


def test_engineering_case_has_traceable_real_seed_sources():
    assert len(ENGINEERING_SEED_SOURCES) >= 5
    assert all(item.get("doi") or "arxiv.org/abs/" in item.get("url", "") for item in ENGINEERING_SEED_SOURCES)
    assert all(item.get("url", "").startswith("https://") for item in ENGINEERING_SEED_SOURCES)
    assert all(item.get("doi") for item in ENGINEERING_SEED_SOURCES[:5])
    acl_source = next(item for item in ENGINEERING_SEED_SOURCES if item.get("doi", "").endswith("findings-acl.422"))
    assert acl_source["title"] == "Document Segmentation Matters for Retrieval-Augmented Generation"


def test_social_case_has_traceable_fulltext_seed_sources():
    assert len(SOCIAL_SEED_SOURCES) >= 5
    assert all(item.get("url", "").startswith("https://") for item in SOCIAL_SEED_SOURCES)
    assert sum(item["url"].lower().endswith(".pdf") for item in SOCIAL_SEED_SOURCES) >= 4
    assert any(item.get("doi") for item in SOCIAL_SEED_SOURCES)
    assert all(item.get("title") and item.get("authors") for item in SOCIAL_SEED_SOURCES)


def test_public_text_corpus_preserves_verified_provenance_and_bounded_extraction():
    downloaded = {
        item["url"]: "\n".join([*item["markers"], "*** START OF THE PROJECT GUTENBERG EBOOK", "body " * 3000])
        for item in PUBLIC_TEXT_SOURCES["humanities"]
    }

    records = build_public_text_corpus("humanities", downloaded)

    assert len(records) == 2
    assert all(item["source_url"] == item["url"] for item in records)
    assert all(item["provenance"] == item["url"] for item in records)
    assert all("first 10,000 characters" in item["content"] for item in records)
    assert all(len(item["content"]) < 10500 for item in records)


def test_public_text_corpus_rejects_wrong_download_instead_of_using_it():
    downloaded = {item["url"]: "wrong document" for item in PUBLIC_TEXT_SOURCES["qualitative"]}

    with pytest.raises(ValueError, match="identity check"):
        build_public_text_corpus("qualitative", downloaded)


def test_attachment_index_preserves_source_url_license_and_provenance(tmp_path):
    run_dir = tmp_path / "run_provenance"
    run_dir.mkdir()
    artifact_manifest_service.initialize(run_dir, run_id="run_provenance", display_name="provenance")
    raw = b"verified primary text"

    extracted = _save_and_extract_attachments("run_provenance", [{
        "name": "primary.txt", "mime_type": "text/plain", "size": len(raw),
        "data_url": "data:text/plain;base64," + base64.b64encode(raw).decode("ascii"),
        "source_url": "https://www.gutenberg.org/ebooks/1", "license": "public domain",
        "provenance": "Project Gutenberg ebook 1",
    }], run_dir)
    persisted = json.loads((run_dir / "inputs" / "attachments.json").read_text(encoding="utf-8"))

    assert extracted == persisted
    assert persisted[0]["source_url"] == "https://www.gutenberg.org/ebooks/1"
    assert persisted[0]["license"] == "public domain"
    assert persisted[0]["provenance"] == "Project Gutenberg ebook 1"


def test_traceable_attachment_becomes_hashed_primary_evidence(tmp_path):
    run_id = "run_attachment_evidence"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    artifact_manifest_service.initialize(run_dir, run_id=run_id, display_name="attachment evidence")
    raw = json.dumps({
        "title": "World Bank education expenditure snapshot by income group",
        "records": [{"income_group": "HIC", "value": 5.1}] * 20,
    }).encode()
    extracted = _save_and_extract_attachments(run_id, [{
        "name": "snapshot.json", "mime_type": "application/json", "size": len(raw),
        "data_url": "data:application/json;base64," + base64.b64encode(raw).decode(),
        "source_url": "https://api.worldbank.org/v2/indicator/example",
        "license": "CC BY 4.0", "provenance": "World Bank API",
    }], run_dir)

    assert _persist_attachment_sources(run_id, extracted) == 1
    evidence = EvidenceRepository.get_by_run(run_id)
    source = evidence["sources"][0]
    assert source["id"].startswith("source_")
    assert source["title"].startswith("World Bank education expenditure")
    assert source["source_type"] == "dataset"
    assert source["metadata"]["origin"] == "user_attachment"
    assert source["metadata"]["citation_eligible"] is True
    assert len(source["metadata"]["content_hash"]) == 64
    assert len(source["metadata"]["snapshot_sha256"]) == 64
    assert evidence["excerpts"] and evidence["excerpts"][0]["excerpt_type"] == "fulltext"
    assert FullTextDocumentRepository.get_by_run(run_id)[0]["parser"] == "uploaded_snapshot"

    normalized_again = evidence_pipeline_service._normalize_source(source, {"run_id": run_id, "id": "task_literature"})
    assert normalized_again["id"] == source["id"]
