from backend.app.services.thesis_quality_service import thesis_quality_service


def _brief() -> dict:
    return {
        "methodology_family": "qualitative",
        "methodology_profile": {"family": "qualitative"},
        "thesis_requirements": {
            "status": "confirmed", "degree_level": "master", "institution": "测试大学",
            "programme": "测试专业", "language": "zh-CN", "citation_style": "GB/T 7714",
            "target_word_count": 1000, "minimum_references": 5, "minimum_supported_claims": 2,
            "required_chapters": ["引言", "文献综述", "方法", "结果", "讨论", "结论"],
        },
    }


def _report() -> str:
    paragraph = "本章基于冻结研究问题、真实材料和明确分析框架展开论证，并保留反例、边界和替代解释。" * 10
    chapters = "\n\n".join(
        f"## {index}. {title}\n\n{paragraph} [{(index % 5) + 1}]"
        for index, title in enumerate(("引言", "文献综述", "方法", "结果", "讨论", "结论"), start=1)
    )
    return f"""# 完整硕士论文测试

## 摘要

{paragraph}

关键词：跨学科；可追溯；研究方法

{chapters}

## 研究贡献与局限

本研究贡献在于建立可追溯结论，同时明确样本局限和外部效度边界。

## 伦理声明与数据可用性

本研究不涉及需要审批的参与者；数据可用性和材料可用范围已在附录声明。

## 参考文献

[1] Reference one.
[2] Reference two.
[3] Reference three.
[4] Reference four.
[5] Reference five.
"""


def _claims() -> list[dict]:
    return [
        {"id": "c1", "status": "supported", "evidence_ids": ["artifact_a"]},
        {"id": "c2", "status": "supported", "evidence_ids": ["artifact_b"]},
    ]


def _tasks() -> list[dict]:
    return [{
        "id": "analysis", "task_type": "result_analysis", "status": "completed",
        "outputs": [{"analysis_artifact": {"family": "qualitative"}}],
    }]


def test_complete_thesis_gate_requires_all_declared_degree_level_conditions():
    result = thesis_quality_service.evaluate(
        _report(), _brief(), _claims(), _tasks(),
        {"sources": [{"id": f"s{i}"} for i in range(5)]}, [],
    )
    assert result["passed"] is True
    assert result["measured_word_count"] >= 1000
    assert result["reference_count"] == 5
    assert all(item["passed"] for item in result["checks"].values())


def test_short_research_report_cannot_be_mislabeled_complete_master_thesis():
    result = thesis_quality_service.evaluate(
        "# 研究报告\n\n## 摘要\n\n很短。\n\n## 参考文献\n\n[1] One.",
        _brief(), _claims(), _tasks(), {"sources": [{"id": "s1"}]}, [],
    )
    assert result["passed"] is False
    assert result["checks"]["length"]["passed"] is False
    assert result["checks"]["required_chapters"]["passed"] is False
    assert result["checks"]["references"]["passed"] is False


def test_required_chapter_heading_without_substance_does_not_pass():
    report = _report()
    report = report.replace(
        "## 4. 结果\n\n" + "本章基于冻结研究问题、真实材料和明确分析框架展开论证，并保留反例、边界和替代解释。" * 10 + " [5]",
        "## 4. 结果\n\n结果见后文。 [5]",
    )
    result = thesis_quality_service.evaluate(
        report, _brief(), _claims(), _tasks(), {"sources": [{"id": "s1"}]}, [],
    )
    assert result["passed"] is False
    assert "结果" in result["checks"]["chapter_substance"]["detail"]


def test_citation_number_without_reference_entry_is_rejected():
    report = _report().replace("明确样本局限", "明确样本局限 [99]")
    result = thesis_quality_service.evaluate(
        report, _brief(), _claims(), _tasks(), {"sources": [{"id": "s1"}]}, [],
    )
    assert result["checks"]["citation_consistency"]["passed"] is False


def test_unconfirmed_institutional_rules_keep_thesis_gate_closed():
    brief = _brief()
    brief["thesis_requirements"]["status"] = "not_provided"
    result = thesis_quality_service.evaluate(
        _report(), brief, _claims(), _tasks(), {"sources": [{"id": "s1"}]}, [],
    )
    assert result["checks"]["institutional_requirements"]["passed"] is False


def test_institutional_word_count_range_is_enforced():
    brief = _brief()
    measured = thesis_quality_service._word_count(_report(), "zh-CN")
    brief["thesis_requirements"].update({
        "minimum_word_count": 1000,
        "target_word_count": measured,
        "maximum_word_count": measured - 1,
    })

    result = thesis_quality_service.evaluate(
        _report(), brief, _claims(), _tasks(), {"sources": [{"id": "s1"}]}, [],
    )

    assert result["checks"]["length"]["passed"] is False
    assert result["maximum_word_count"] == measured - 1
