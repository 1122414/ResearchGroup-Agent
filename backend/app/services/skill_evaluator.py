import re

from ..core.config import settings


SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)\.env"),
    re.compile(r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----"),
]


class SkillEvaluator:
    def evaluate(self, candidate: dict) -> dict:
        text = "\n".join(
            [
                str(candidate.get("title", "")),
                str(candidate.get("description", "")),
                str(candidate.get("content", "")),
                " ".join(candidate.get("tags", [])),
            ]
        )
        if settings.skill_sensitive_scan_enabled and self.has_sensitive_content(text):
            return {"accepted": False, "confidence": 0.0, "reason": "候选内容包含敏感信息或环境变量痕迹"}

        reusability = self._score_reusability(text)
        specificity = self._score_specificity(text)
        safety = 1.0
        novelty = 0.7 if len(text) > 220 else 0.4
        confidence = round((reusability * 0.35) + (specificity * 0.35) + (safety * 0.2) + (novelty * 0.1), 2)
        accepted = (
            reusability >= 0.7
            and specificity >= 0.65
            and safety >= 0.9
            and novelty >= 0.5
            and confidence >= settings.skill_min_confidence
        )
        return {
            "accepted": accepted,
            "confidence": confidence,
            "reason": "满足沉淀标准" if accepted else "候选经验不够具体或复用价值不足",
            "scores": {
                "reusability": reusability,
                "specificity": specificity,
                "safety": safety,
                "novelty": novelty,
            },
        }

    def has_sensitive_content(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)

    def _score_reusability(self, text: str) -> float:
        keywords = ["步骤", "模板", "复用", "检查", "流程", "指标", "风险", "适用", "触发", "避免", "验证"]
        hits = sum(1 for keyword in keywords if keyword in text)
        return min(1.0, 0.35 + hits * 0.1)

    def _score_specificity(self, text: str) -> float:
        bullet_count = text.count("- ") + text.count("1.")
        has_sections = all(section in text for section in ("适用场景", "操作步骤", "反例"))
        length_score = min(0.45, len(text) / 1000)
        return min(1.0, length_score + bullet_count * 0.08 + (0.35 if has_sections else 0.0))


skill_evaluator = SkillEvaluator()
