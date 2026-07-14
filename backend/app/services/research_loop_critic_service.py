from __future__ import annotations


class ResearchLoopCriticService:
    """Deterministic critic kept independent from the action-generating LLM path."""

    ALLOWED_TOOLS = {"evidence_search", "experiment_runner", "result_analyzer"}

    def review(self, candidate: dict, seen_fingerprints: set[str], state: dict) -> dict:
        reasons: list[str] = []
        if candidate["fingerprint"] in seen_fingerprints:
            reasons.append("duplicate_action")
        if candidate["selected_tool"] not in self.ALLOWED_TOOLS:
            reasons.append("tool_not_allowed")
        if candidate["safety_level"] == "high":
            reasons.append("high_risk_requires_human")
        if candidate["selected_tool"] == "experiment_runner" and not candidate.get("dataset_ready"):
            reasons.append("experiment_dataset_not_ready")
        target_id = candidate.get("target", {}).get("id")
        if not target_id:
            reasons.append("missing_target")

        information_gain = float(candidate.get("expected_information_gain") or 0)
        cost_penalty = min(float(candidate.get("estimated_cost") or 0) / 10, 0.3)
        risk_penalty = {"low": 0.0, "medium": 0.15, "high": 0.5}.get(candidate["safety_level"], 0.5)
        score = round(information_gain - cost_penalty - risk_penalty, 4)
        if score < float(state.get("minimum_information_gain") or 0):
            reasons.append("marginal_information_gain_too_low")
        return {
            "approved": not reasons,
            "score": score,
            "reasons": reasons,
            "reviewer": "deterministic_independent_critic_v1",
        }


research_loop_critic_service = ResearchLoopCriticService()
