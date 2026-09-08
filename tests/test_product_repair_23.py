"""PRODUCT-REPAIR-23 contracts: repository evidence activation fallback.

The frozen routing priority (CHANGE_TEST → DOCS_CODE → THEORY_CODE →
DIAGNOSIS → PROJECT_CODE → NO_ADDITIONAL) is unchanged; only the final
PROJECT_CODE fallback is extended so that questions about the bound
repository's source, module/function/file location, or call relationships
activate PROJECT_CODE_V1 even without an explicit project-scope qualifier.
Generic technology-knowledge questions must stay unrouted.
"""

from __future__ import annotations

from pathlib import Path

from core.engineering_requirements import (
    CHANGE_TEST_V1,
    DIAGNOSIS_CROSS_FILE_V1,
    DIAGNOSIS_SINGLE_V1,
    DOCS_CODE_V1,
    FROZEN_PROFILE_SPECS,
    NO_ADDITIONAL_REQUIREMENT,
    PROJECT_CODE_V1,
    THEORY_CODE_V1,
    route_engineering_evidence_requirement,
)


class TestRepositoryNavigationActivation:
    def test_card_acceptance_questions_activate_project_code(self):
        for question in (
            "这个源码在哪里？",
            "这个模块在哪个文件实现？",
            "这个函数是谁调用的？",
            "请结合源码说明它的实现",
        ):
            assert (
                route_engineering_evidence_requirement(question).requirement_profile
                is PROJECT_CODE_V1
            ), question

    def test_source_reference_alone_names_the_bound_repository(self):
        for question in (
            "这个仓库的源码结构是怎样的？",
            "请结合源码说明这个能力的边界",
            "Explain how the retry chain works in the source code",
        ):
            assert (
                route_engineering_evidence_requirement(question).requirement_profile
                is PROJECT_CODE_V1
            ), question

    def test_module_and_function_location_questions_activate(self):
        for question in (
            "这个模块在哪里？",
            "核心逻辑在哪里实现？",
            "实现位置在哪里？",
            "重试逻辑在哪里定义？",
            "Which file contains the entry function?",
            "Where is the validation module implemented?",
        ):
            assert (
                route_engineering_evidence_requirement(question).requirement_profile
                is PROJECT_CODE_V1
            ), question

    def test_call_relationship_questions_activate(self):
        for question in (
            "这个函数是谁调用的？",
            "查询入口的调用链是什么？",
            "这个方法的调用者有哪些？",
            "Who calls the response handler?",
            "Trace the call chain from the client entry",
        ):
            assert (
                route_engineering_evidence_requirement(question).requirement_profile
                is PROJECT_CODE_V1
            ), question

    def test_generic_knowledge_questions_are_not_forced_to_project_code(self):
        for question in (
            "RAG 的基本原理是什么？",
            "RAG 一般是怎么实现的？",
            "Transformer 是怎么实现 Attention 的？",
            "Java HashMap 原理是什么？",
            "RAG 检索的核心机制有哪些？",
            "How does attention work in general?",
            "How do I greet the user?",
            "如何打印一条普通日志？",
        ):
            assert (
                route_engineering_evidence_requirement(question).requirement_profile
                is NO_ADDITIONAL_REQUIREMENT
            ), question

    def test_concept_questions_with_repository_word_stay_unrouted(self):
        assert (
            route_engineering_evidence_requirement(
                "Explain an agent runtime concept without inspecting a repository"
            ).requirement_profile
            is NO_ADDITIONAL_REQUIREMENT
        )
        assert (
            route_engineering_evidence_requirement(
                "The code has an error"
            ).requirement_profile
            is NO_ADDITIONAL_REQUIREMENT
        )


class TestRoutingPriorityUnchanged:
    def test_frozen_profile_shapes_are_unchanged(self):
        expected = {
            PROJECT_CODE_V1: ((("project_code",),), 1),
            NO_ADDITIONAL_REQUIREMENT: ((), 0),
        }
        for profile, spec in expected.items():
            assert FROZEN_PROFILE_SPECS[profile] == spec

    def test_higher_priority_domains_still_win(self):
        assert (
            route_engineering_evidence_requirement(
                "审查这次变更和回归测试"
            ).requirement_profile
            is CHANGE_TEST_V1
        )
        assert (
            route_engineering_evidence_requirement(
                "Is the README documentation still accurate for the current implementation?"
            ).requirement_profile
            is DOCS_CODE_V1
        )
        assert (
            route_engineering_evidence_requirement(
                "解释原理并结合当前源码实现进行对照"
            ).requirement_profile
            is THEORY_CODE_V1
        )
        assert (
            route_engineering_evidence_requirement(
                "诊断配置项的校验失败路径"
            ).requirement_profile
            is DIAGNOSIS_SINGLE_V1
        )
        assert (
            route_engineering_evidence_requirement(
                "诊断失败在组件之间的传播调用链"
            ).requirement_profile
            is DIAGNOSIS_CROSS_FILE_V1
        )

    def test_scope_qualified_questions_keep_original_project_route(self):
        assert (
            route_engineering_evidence_requirement(
                "检查当前仓库源码的依赖边界"
            ).requirement_profile
            is PROJECT_CODE_V1
        )


class TestNoScenarioSpecificBinding:
    def test_router_stays_free_of_set_a_case_specific_words(self):
        source = (
            Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("core", "engineering_requirements.py")
            .read_text(encoding="utf-8")
        )
        for marker in (
            "vanna",
            "instructor",
            "ToolRegistry",
            "from_openai",
            "HyDE",
        ):
            assert marker not in source, marker
