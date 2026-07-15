from backend.app.services.experiment_result_service import ExperimentResultService


def test_generic_supports_when_treatment_beats_baseline_maximize():
    metrics = {"metric_name": "accuracy", "baseline_value": 0.6, "treatment_value": 0.8, "direction": "maximize"}
    relation, confidence, _ = ExperimentResultService._interpret(metrics, "completed")
    assert relation == "supports"
    assert confidence > 0.6


def test_generic_rejects_when_treatment_worse_minimize():
    metrics = {"metric_name": "latency_ms", "baseline_value": 100, "treatment_value": 150, "direction": "minimize"}
    relation, _, _ = ExperimentResultService._interpret(metrics, "completed")
    assert relation == "rejects"


def test_generic_weakens_on_tie():
    metrics = {"metric_name": "f1", "baseline_value": 0.5, "treatment_value": 0.5, "direction": "maximize"}
    relation, _, _ = ExperimentResultService._interpret(metrics, "completed")
    assert relation == "weakens"


def test_legacy_rag_contract_still_supported():
    metrics = {
        "best_strategy": {"strategy": "fixed_100_overlap_30", "mrr": 0.8, "top3_accuracy": 0.9},
        "rows": [{"strategy": "no_split", "mrr": 0.5}],
        "statistical_analysis": {"relative_effect": 0.6, "confidence_interval_95": [0.2, 0.4]},
    }
    relation, _, _ = ExperimentResultService._interpret(metrics, "completed")
    assert relation == "supports"


def test_retrieval_summary_uses_mrr_at_10():
    summary = ExperimentResultService._summary(
        "completed",
        {"best_strategy": {"strategy": "overlap", "top3_accuracy": 1.0, "mrr_at_10": 0.75}},
        {},
    )
    assert "mrr_at_10=0.75" in summary
    assert "None" not in summary


def test_failure_is_inconclusive():
    relation, _, _ = ExperimentResultService._interpret({}, "failed")
    assert relation == "inconclusive"


def test_synthetic_demo_cannot_support_hypothesis():
    metrics = {
        "publishable": False,
        "best_strategy": {"strategy": "demo", "mrr": 1.0},
        "rows": [{"strategy": "no_split", "mrr": 0.0}],
    }
    relation, confidence, message = ExperimentResultService._interpret(metrics, "completed")
    assert relation == "inconclusive"
    assert confidence == 0.0
    assert "合成" in message
