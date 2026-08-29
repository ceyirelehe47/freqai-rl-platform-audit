"""工作包 E:first_pass Attempt 选择策略硬约束(E2/E3)。

负例全部拒绝:两个 accept、重复编号、编号跳跃、编号超出 max、
selected 后还有记录、selected 前已有 accept、没有 accept 但提供
pack、attempt log 与实际输出 pack hash 不一致。
"""

from __future__ import annotations

import pytest

from conftest import LOG_V2

from rl_curriculum.builder_provenance import (
    BuilderProvenanceError,
    attempt_log_hash,
    canonicalize_attempt_log,
    check_attempt_log,
)

POLICY = {"policy": "first_pass", "max_attempts": 5}


def _log(attempts, selected, output_pack_hash="p-x", max_attempts=5):
    return {
        "format": LOG_V2,
        "max_attempts": max_attempts,
        "attempts": [
            {"attempt": a, "verdict": v,
             "reject_reasons": r if v == "reject" else []}
            for a, v, r in attempts
        ],
        "selected_attempt": selected,
        "output_pack_hash": output_pack_hash,
    }


R = ("reject", ["reason"])


def test_valid_first_pass_log_accepted():
    log = _log([(0, "reject", ["a"]), (1, "reject", ["b"]),
                (2, "accept", [])], 2)
    check_attempt_log(log, attempt_policy=POLICY)


def test_accept_at_zero_selected_zero():
    log = _log([(0, "accept", [])], 0)
    check_attempt_log(log, attempt_policy=POLICY)


def test_no_accept_build_failed_shape_allowed():
    """全部尝试耗尽后失败(无选中)是合法的失败日志。"""
    log = _log([(0, "reject", ["a"]), (1, "reject", ["b"])], None)
    check_attempt_log(log, attempt_policy=POLICY)


def test_two_accepts_rejected():
    log = _log([(0, "accept", []), (1, "accept", [])], 1)
    with pytest.raises(BuilderProvenanceError, match="accept"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_duplicate_attempt_numbers_rejected():
    log = _log([(0, "reject", ["a"]), (0, "reject", ["b"]),
                (1, "accept", [])], 1)
    with pytest.raises(BuilderProvenanceError, match="连续"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_number_gap_rejected():
    log = _log([(0, "reject", ["a"]), (2, "accept", [])], 2)
    with pytest.raises(BuilderProvenanceError, match="连续"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_number_not_starting_at_zero_rejected():
    log = _log([(1, "accept", [])], 1)
    with pytest.raises(BuilderProvenanceError, match="连续"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_number_beyond_max_rejected():
    log = _log(
        [(i, "reject", [f"p{i}"]) for i in range(5)] + [(5, "accept", [])],
        5, max_attempts=5)
    with pytest.raises(BuilderProvenanceError, match="超出|max"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_entries_after_selected_rejected():
    """选中 attempt 2 之后还有条目(后选/复选)拒绝。"""
    log = _log([(0, "reject", ["a"]), (1, "accept", []),
                (2, "reject", ["later"])], 1)
    with pytest.raises(BuilderProvenanceError, match="之后"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_selected_not_first_accept_rejected():
    """attempt 0 已 accept,却选择 attempt 1(跳过更早合格)拒绝。"""
    log = _log([(0, "accept", []), (1, "accept", [])], 1)
    with pytest.raises(BuilderProvenanceError, match="accept|第一个"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_accept_before_selected_rejected():
    """selected 指向 accept 但之前还有一个 accept(两个 accept 变体)。"""
    log = _log([(0, "reject", ["a"]), (1, "reject", ["b"]),
                (2, "accept", [])], 2)
    # 该形态合法;构造违规变体:把 selected 指向 2 但 attempts 前部
    # 混入 accept
    bad = _log([(0, "reject", ["a"]), (1, "accept", []),
                (2, "accept", [])], 2)
    with pytest.raises(BuilderProvenanceError, match="accept"):
        check_attempt_log(bad, attempt_policy=POLICY)
    check_attempt_log(log, attempt_policy=POLICY)  # 对照组合法


def test_accept_without_selection_rejected():
    """存在 accept 条目但未选中:构建必须失败,不得产出 pack。"""
    log = _log([(0, "accept", [])], None)
    with pytest.raises(BuilderProvenanceError, match="未选中"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_output_pack_hash_recomputed_by_canonicalize():
    """canonicalize 以主进程实际解析的 pack hash 覆盖 stale 值:
    builder 自报的 output_pack_hash 不是信任源,绑定值永远来自
    主进程(与 evidence 层 output_pack_hash==pack_hash 对账联动)。"""
    raw = _log([(0, "reject", ["a"]), (1, "accept", [])], 1,
               output_pack_hash="p-stale")
    log = canonicalize_attempt_log(
        raw, output_pack_hash="p-actual", attempt_policy=POLICY)
    assert log["output_pack_hash"] == "p-actual"
    assert attempt_log_hash(log) != _log_hash_with("p-stale")


def _log_hash_with(pack_hash):
    log = _log([(0, "reject", ["a"]), (1, "accept", [])], 1,
               output_pack_hash=pack_hash)
    return attempt_log_hash(log)


def test_log_v1_format_rejected():
    log = _log([(0, "accept", [])], 0)
    log["format"] = "builder-attempt-log-v1"
    with pytest.raises(BuilderProvenanceError, match="format"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_policy_bound_to_request():
    """log.max_attempts 与 attempt_policy 上限不一致拒绝(不得漂移)。"""
    log = _log([(0, "accept", [])], 0, max_attempts=9)
    with pytest.raises(BuilderProvenanceError, match="不一致"):
        check_attempt_log(log, attempt_policy=POLICY)


def test_assembly_policy_must_be_empty():
    """assembly 策略必须空日志(公开组装通道)。"""
    ok = {
        "format": LOG_V2, "max_attempts": 0, "attempts": [],
        "selected_attempt": None, "output_pack_hash": "p-x",
    }
    check_attempt_log(ok, attempt_policy={
        "policy": "assembly", "max_attempts": 0})
    bad = {
        "format": LOG_V2, "max_attempts": 0,
        "attempts": [{"attempt": 0, "verdict": "accept",
                      "reject_reasons": []}],
        "selected_attempt": 0, "output_pack_hash": "p-x",
    }
    with pytest.raises(BuilderProvenanceError, match="组装模式|assembly"):
        check_attempt_log(bad, attempt_policy={
            "policy": "assembly", "max_attempts": 0})


def test_runner_rejects_late_selection(sealed_exam_env, tmp_path):
    """E2 端到端:攻击 builder 选中第二个 accept(跳过首个合格)。
    真实隔离 Runner 必须拒绝采信其产物。"""
    from rl_curriculum.builder_evidence import _run_once_for_mode
    from rl_curriculum.builder_provenance import BuilderProvenanceError
    from conftest import attack_request, write_attack_builder
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )

    src = (
        "def build_pack(request):\n"
        "    pack = {\n"
        "        'schema': 'exam-pack-v1', 'name': request['pack_name'],\n"
        "        'version': request['pack_version'],\n"
        "        'visibility': 'mock_hidden', 'charter_hash': '',\n"
        "        'spec_versions': {}, 'timeframe': request['timeframe'],\n"
        "        'episodes': [{'family': 'probe_null_sign',\n"
        "                      'params': {'episode_bars': 96}, 'seed': 1,\n"
        "                      'split': 'null_control',\n"
        "                      'timeframe': request['timeframe']}],\n"
        "        'notes': {}}\n"
        "    log = {'format': 'builder-attempt-log-v2',\n"
        "           'max_attempts': 4,\n"
        "           'attempts': [\n"
        "            {'attempt': 0, 'verdict': 'accept',\n"
        "             'reject_reasons': []},\n"
        "            {'attempt': 1, 'verdict': 'accept',\n"
        "             'reject_reasons': []}],\n"
        "           'selected_attempt': 1}\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'ok', 'pack': pack,\n"
        "            'attempt_log': log, 'error': None}\n"
    )
    root = tmp_path / "late_select"
    root.mkdir(parents=True)
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    (root / "provider_config.json").write_text(
        '{"entrypoint_module": "builder_attack", '
        '"entrypoint_qualname": "build_pack", '
        '"families": ["probe_null_sign"], "pair_count_per_family": 2, '
        '"max_attempts": 4, "root_label": "late-select"}',
        encoding="utf-8")
    provider = private_provider_from_root(root)
    req = attack_request(provider, sealed_exam_env["pack"],
                         _dc(sealed_exam_env))
    with pytest.raises(BuilderProvenanceError, match="accept|Runner"):
        _run_once_for_mode(provider, req, builder_root=root)


def _dc(sealed_exam_env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        sealed_exam_env["pack"], required_families=[
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"])
