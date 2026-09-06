"""Provider-free tests for the ARCH-INTEGRATION-12A-R1 identity boundary."""

from __future__ import annotations

import copy
import json

import pytest

from core.tool_agent.default_tools import CODE_SEARCH_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_VERSION
from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    FROZEN_SYSTEM_A_BASE_TOOLSET_SHA256,
    FROZEN_SYSTEM_A_EFFECTIVE_TOOLSET_SHA256,
    FROZEN_SYSTEM_B_BASE_TOOLSET_SHA256,
    FROZEN_SYSTEM_B_EFFECTIVE_TOOLSET_SHA256,
    GOLD_PROOF_AUDIT_PATH,
    HOLDOUT_DATASET_PATH,
    ProtocolViolation,
    _computed_protocol_sha256,
    load_protocol_manifest,
    validate_protocol_manifest,
)


def _self_consistent_manifest(tmp_path, mutate):
    manifest = copy.deepcopy(load_protocol_manifest())
    mutate(manifest)
    manifest["protocol_sha256"] = _computed_protocol_sha256(manifest)

    for source in (DEV_DATASET_PATH, HOLDOUT_DATASET_PATH, GOLD_PROOF_AUDIT_PATH):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    manifest_path = tmp_path / "protocol_manifest_v1.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest_path


def test_live_code_search_v5_keeps_frozen_protocol_valid():
    assert CODE_SEARCH_VERSION == "code_search_v5"
    assert CODE_SEARCH_SPEC.version == CODE_SEARCH_VERSION
    manifest = validate_protocol_manifest()
    assert manifest["protocol_sha256"] == (
        "281dba7b098535fd508971bfdd98d53ae188c8efa204b5c1fa929c3a40d6a40d"
    )


def test_frozen_system_a_rejects_a_self_consistent_other_64_hex_sha(tmp_path):
    def mutate(manifest):
        toolset = manifest["systems"]["A"]["toolset"]
        replacement = "a" * 64
        toolset["sha256"] = replacement
        toolset["base_registry"]["sha256"] = replacement
        toolset["effective_dynamic_registry"]["sha256"] = replacement

    path = _self_consistent_manifest(tmp_path, mutate)
    with pytest.raises(ProtocolViolation, match="System A .*SHA drift"):
        validate_protocol_manifest(path)


def test_frozen_system_b_effective_rejects_a_self_consistent_other_64_hex_sha(tmp_path):
    def mutate(manifest):
        manifest["systems"]["B"]["toolset"]["effective_dynamic_registry"][
            "sha256"
        ] = "b" * 64

    path = _self_consistent_manifest(tmp_path, mutate)
    with pytest.raises(ProtocolViolation, match="System B effective toolset SHA drift"):
        validate_protocol_manifest(path)


def test_frozen_toolset_constants_are_explicit_and_not_live_recomputed():
    assert FROZEN_SYSTEM_A_BASE_TOOLSET_SHA256 == (
        "9b846d9e72e8d5536c2b3de8730f61433a96d7ff59f557a70f07c6a0c33bb85f"
    )
    assert FROZEN_SYSTEM_A_EFFECTIVE_TOOLSET_SHA256 == FROZEN_SYSTEM_A_BASE_TOOLSET_SHA256
    assert FROZEN_SYSTEM_B_BASE_TOOLSET_SHA256 == FROZEN_SYSTEM_A_BASE_TOOLSET_SHA256
    assert FROZEN_SYSTEM_B_EFFECTIVE_TOOLSET_SHA256 == (
        "8d0bca387ffef15bd0fc001439bf6581c8dbd5279efd63686ae19d775d05133c"
    )
