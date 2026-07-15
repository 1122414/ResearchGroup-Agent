from benchmarks.run_real_thesis import (
    ENGINEERING_SEED_SOURCES,
    build_social_dataset,
    engineering_contract,
    social_contract,
)


def test_real_thesis_contracts_freeze_actual_programme_limits():
    engineering = engineering_contract()["thesis_requirements"]
    social = social_contract()["thesis_requirements"]

    assert engineering["maximum_word_count"] == 8000
    assert "drps.ed.ac.uk" in engineering["requirements_source"]
    assert social["maximum_word_count"] == 15000
    assert "sps.ed.ac.uk" in social["requirements_source"]


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
    assert len(ENGINEERING_SEED_SOURCES) == 5
    assert all(item.get("doi") or "arxiv.org/abs/" in item.get("url", "") for item in ENGINEERING_SEED_SOURCES)
    assert all(item.get("url", "").startswith("https://") for item in ENGINEERING_SEED_SOURCES)
