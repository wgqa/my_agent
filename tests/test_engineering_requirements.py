from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.engineering_requirements import (
    CHANGE_TEST_V1,
    DIAGNOSIS_CROSS_FILE_V1,
    DIAGNOSIS_SINGLE_V1,
    DOCS_CODE_V1,
    NO_ADDITIONAL_REQUIREMENT,
    PROJECT_CODE_V1,
    THEORY_CODE_V1,
    EngineeringEvidenceRequirement,
    EngineeringRequirementProfile,
    evaluate_evidence_requirement,
    route_engineering_evidence_requirement,
)
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence


def _code(path: str) -> EngineeringEvidence:
    return EngineeringEvidence(
        evidence_id="E1",
        kind="project_code",
        path=path,
        start_line=1,
        end_line=1,
        snippet="synthetic source",
    )


def _test(path: str = "tests/test_synthetic.py") -> EngineeringEvidence:
    return EngineeringEvidence(
        evidence_id="E1",
        kind="project_test",
        path=path,
        start_line=1,
        end_line=1,
        snippet="assert synthetic_behavior()",
    )


def _doc() -> EngineeringEvidence:
    return EngineeringEvidence(
        evidence_id="E1",
        kind="project_doc",
        path="README.md",
        start_line=1,
        end_line=1,
        snippet="synthetic documentation",
    )


def _change() -> EngineeringEvidence:
    return EngineeringEvidence(
        evidence_id="E1",
        kind="project_change",
        path="src/service.py",
        start_line=1,
        end_line=1,
        snippet="@@ synthetic diff",
    )


def _knowledge() -> KnowledgeEvidence:
    return KnowledgeEvidence(
        evidence_id="E1",
        kind="knowledge",
        source_name="knowledge/synthetic.md",
        chunk_id="synthetic-1",
        score=1.0,
        rank=1,
        snippet="synthetic knowledge",
    )


class TestFrozenRequirements:
    def test_exact_frozen_profiles(self):
        assert EngineeringEvidenceRequirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        ).required_evidence_groups == (("project_change",), ("project_test",))
        assert EngineeringEvidenceRequirement(
            THEORY_CODE_V1,
            (("knowledge",), ("project_code", "project_doc")),
            1,
        ).min_distinct_project_code_paths == 1
        assert EngineeringEvidenceRequirement(
            DIAGNOSIS_SINGLE_V1,
            (("project_code",),),
            1,
        ).requirement_profile is EngineeringRequirementProfile.DIAGNOSIS_SINGLE_V1
        assert EngineeringEvidenceRequirement(
            DIAGNOSIS_CROSS_FILE_V1,
            (("project_code",),),
            2,
        ).min_distinct_project_code_paths == 2
        assert EngineeringEvidenceRequirement(
            DOCS_CODE_V1,
            (("project_doc",), ("project_code",)),
            1,
        ).required_evidence_groups == (("project_doc",), ("project_code",))
        assert EngineeringEvidenceRequirement(
            NO_ADDITIONAL_REQUIREMENT,
            (),
            0,
        ).required_evidence_groups == ()

    def test_requirement_is_immutable_and_profile_shape_is_frozen(self):
        requirement = EngineeringEvidenceRequirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        with pytest.raises(FrozenInstanceError):
            requirement.min_distinct_project_code_paths = 1
        with pytest.raises(ValueError):
            EngineeringEvidenceRequirement(
                CHANGE_TEST_V1,
                (("project_change", "project_change"), ("project_test",)),
                0,
            )
        with pytest.raises(ValueError):
            EngineeringEvidenceRequirement(
                CHANGE_TEST_V1,
                (("project_change",), ("changed_files",)),
                0,
            )
        with pytest.raises(ValueError):
            EngineeringEvidenceRequirement(
                DIAGNOSIS_CROSS_FILE_V1,
                (("project_code",),),
                1,
            )


class TestEvidenceShape:
    def test_and_of_or_and_ignored_observation(self):
        requirement = EngineeringEvidenceRequirement(
            THEORY_CODE_V1,
            (("knowledge",), ("project_code", "project_doc")),
            1,
        )
        state = evaluate_evidence_requirement(
            requirement,
            [
                {"kind": "changed_files", "path": "tests/test_synthetic.py"},
                _knowledge(),
                _doc(),
            ],
        )
        assert state.satisfied is True
        assert state.evidence_kind_counts["knowledge"] == 1
        assert state.evidence_kind_counts["project_doc"] == 1
        assert state.evidence_kind_counts["project_code"] == 0
        with pytest.raises(TypeError):
            state.evidence_kind_counts["knowledge"] = 2

    def test_change_test_requires_project_test_not_candidate_provenance(self):
        requirement = EngineeringEvidenceRequirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        state = evaluate_evidence_requirement(
            requirement,
            [_change(), {"kind": "changed_files", "path": "tests/test_synthetic.py"}],
        )
        assert state.satisfied is False
        assert state.missing_evidence_groups == (("project_test",),)

        complete = evaluate_evidence_requirement(requirement, [_change(), _test()])
        assert complete.satisfied is True

    def test_cross_file_path_shortfall_is_not_a_missing_kind_group(self):
        requirement = EngineeringEvidenceRequirement(
            DIAGNOSIS_CROSS_FILE_V1,
            (("project_code",),),
            2,
        )
        state = evaluate_evidence_requirement(requirement, [_code("src/one.py")])
        assert state.satisfied is False
        assert state.missing_evidence_groups == ()
        assert state.distinct_project_code_paths == 1
        assert state.required_min_distinct_project_code_paths == 2
        complete = evaluate_evidence_requirement(
            requirement,
            [_code("src/one.py"), _code("src/two.py")],
        )
        assert complete.satisfied is True


class TestSyntheticRouter:
    def test_english_positive_and_unmatched_queries(self):
        assert route_engineering_evidence_requirement(
            "Review the commit diff and regression test"
        ).requirement_profile is CHANGE_TEST_V1
        assert route_engineering_evidence_requirement(
            "Explain the theory and compare it with the current implementation"
        ).requirement_profile is THEORY_CODE_V1
        assert route_engineering_evidence_requirement(
            "How do I greet the user?"
        ).requirement_profile is NO_ADDITIONAL_REQUIREMENT

    def test_chinese_positive_and_negative_queries(self):
        assert route_engineering_evidence_requirement(
            "审查这次变更和回归测试"
        ).requirement_profile is CHANGE_TEST_V1
        assert route_engineering_evidence_requirement(
            "解释机制并结合当前实现进行对照"
        ).requirement_profile is THEORY_CODE_V1
        assert route_engineering_evidence_requirement(
            "如何打印一条普通日志？"
        ).requirement_profile is NO_ADDITIONAL_REQUIREMENT

    def test_docs_and_diagnosis_profiles(self):
        assert route_engineering_evidence_requirement(
            "Is the README documentation still accurate for the current implementation?"
        ).requirement_profile is DOCS_CODE_V1
        assert route_engineering_evidence_requirement(
            "Diagnose the validation error and its runtime behavior"
        ).requirement_profile is DIAGNOSIS_SINGLE_V1
        assert route_engineering_evidence_requirement(
            "Diagnose failure propagation across modules"
        ).requirement_profile is DIAGNOSIS_CROSS_FILE_V1

    def test_project_domain_profiles_cover_current_engineering_questions(self):
        assert route_engineering_evidence_requirement(
            "Review the current project code for the runtime facade"
        ).requirement_profile is PROJECT_CODE_V1
        assert route_engineering_evidence_requirement(
            "只回答当前问题：如何把 bounded conversation context 组合成 standalone intent？"
        ).requirement_profile is PROJECT_CODE_V1
        assert route_engineering_evidence_requirement(
            "核对项目文档对 evidence-grounded engineering agent 的定位，判断文档是否把知识库误写成独立 Agent。"
        ).requirement_profile is DOCS_CODE_V1
        assert route_engineering_evidence_requirement(
            "Documentation versus implementation"
        ).requirement_profile is DOCS_CODE_V1
        assert route_engineering_evidence_requirement(
            "当 trace 显示多个预算字段时，如何诊断是否出现了两个逻辑 Budget Owner？"
        ).requirement_profile is DIAGNOSIS_CROSS_FILE_V1

    def test_precedence_and_ambiguous_signals(self):
        assert route_engineering_evidence_requirement(
            "Compare the documentation and code after the change and test regression"
        ).requirement_profile is CHANGE_TEST_V1
        assert route_engineering_evidence_requirement(
            "Compare theory with the implementation"
        ).requirement_profile is THEORY_CODE_V1
        assert route_engineering_evidence_requirement(
            "The code has an error"
        ).requirement_profile is NO_ADDITIONAL_REQUIREMENT

    def test_router_production_code_has_no_evaluator_or_benchmark_binding(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        paths = (
            root / "core" / "engineering_requirements.py",
            root / "core" / "engineering_agent.py",
            root / "core" / "tool_agent" / "runtime.py",
            root / "core" / "tool_agent" / "runtime_models.py",
        )
        forbidden = (
            "evaluation.gate12",
            "g12q",
            "g12c",
            "gate12-v1",
            "465dd65",
            "bfa8e918",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            assert not any(marker in text for marker in forbidden), path
