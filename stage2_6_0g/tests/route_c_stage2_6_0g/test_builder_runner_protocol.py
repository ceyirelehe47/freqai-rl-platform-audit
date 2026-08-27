"""A2:统一 Builder Runner 调用协议(builder-runner-protocol-v1)。

冻结构建请求的黑名单/格式/哈希;入口执行的规范化结果;返回 None、
抛异常、非 dict、status 非 ok、pack 缺失或不可解析一律 failed。
"""

from __future__ import annotations

import pytest

from rl_curriculum.builder_provenance import (
    BUILD_REQUEST_FORMAT,
    BUILDER_RUNNER_PROTOCOL,
    build_frozen_build_request,
    check_frozen_build_request,
    frozen_build_request_hash,
    run_builder_entrypoint,
)


def _base_request(**over):
    req = {
        "format": BUILD_REQUEST_FORMAT,
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "builder_protocol": "null-pack-builder-protocol-v3",
        "builder_manifest_hash": "npb-" + "0" * 64,
        "pack_name": "x",
        "pack_version": "x",
        "pack_timeframe": "15m",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 32,
        "max_attempts": 8,
        "params_spec": {"episode_bars": 96},
        "timeframe": "15m",
        "resolved_bars": 96,
        "resolved_duration_hours": 24.0,
        "duration_contract_hash": "ndc-" + "0" * 64,
    }
    req.update(over)
    return req


def test_request_format_enforced():
    with pytest.raises(Exception, match="格式"):
        check_frozen_build_request({"format": "builder-build-request-v0"})
    with pytest.raises(Exception, match="dict"):
        check_frozen_build_request("not-a-dict")
    check_frozen_build_request(_base_request())  # 合法请求通过


def test_request_required_fields_enforced():
    for field in ("builder_manifest_hash", "families", "params_spec",
                  "timeframe", "resolved_bars", "duration_contract_hash"):
        req = _base_request()
        req[field] = None
        with pytest.raises(Exception, match="必填字段"):
            check_frozen_build_request(req)
    # 数值字段的 0 同样是缺省(resolved_bars=0 / pair 数=0 无意义)
    for field in ("resolved_bars", "pair_count_per_family", "max_attempts"):
        req = _base_request()
        req[field] = 0
        with pytest.raises(Exception, match="必填字段"):
            check_frozen_build_request(req)


@pytest.mark.parametrize("bad", ["candidate", "checkpoint", "model",
                                 "policy", "score", "verdict"])
def test_request_forbidden_fields_rejected(bad):
    """构建请求不得包含候选字段(顶层与嵌套一律拒绝;A2)。"""
    req = _base_request()
    req[bad] = "anything"
    with pytest.raises(Exception, match="禁止字段"):
        check_frozen_build_request(req)
    # 嵌套隐藏也被拒绝
    req2 = _base_request()
    req2["params_spec"] = {"nested": {bad: 1}}
    with pytest.raises(Exception, match="禁止字段"):
        check_frozen_build_request(req2)
    # list 内 dict 同样拒绝
    req3 = _base_request()
    req3["families"] = [{"name": "x", bad: 2}]
    with pytest.raises(Exception, match="禁止字段"):
        check_frozen_build_request(req3)


def test_request_hash_stable_and_prefixed():
    h1 = frozen_build_request_hash(_base_request())
    h2 = frozen_build_request_hash(_base_request())
    assert h1 == h2 and h1.startswith("nbr-")
    changed = _base_request(pair_count_per_family=16)
    assert frozen_build_request_hash(changed) != h1


def test_runner_returns_none_failed():
    """P2 核心:入口返回 None -> failed(不与任何 pack 组合通过)。"""
    result = run_builder_entrypoint(
        lambda request: None, _base_request())
    assert result["status"] == "failed"
    assert result["pack"] is None
    assert "None" in result["error"]


def test_runner_exception_failed():
    def boom(request):
        raise RuntimeError("builder exploded")

    result = run_builder_entrypoint(boom, _base_request())
    assert result["status"] == "failed"
    assert "RuntimeError" in result["error"]


def test_runner_non_dict_failed():
    result = run_builder_entrypoint(
        lambda request: "ok-but-string", _base_request())
    assert result["status"] == "failed"
    assert "不是规范化结果" in result["error"]


def test_runner_self_reported_failure_failed():
    result = run_builder_entrypoint(
        lambda request: {"status": "failed", "error": "x",
                         "attempt_log": []}, _base_request())
    assert result["status"] == "failed"


def test_runner_missing_pack_failed():
    result = run_builder_entrypoint(
        lambda request: {"status": "ok", "attempt_log": []},
        _base_request())
    assert result["status"] == "failed"
    assert "缺少 pack" in result["error"]


def test_runner_unparsable_pack_failed():
    result = run_builder_entrypoint(
        lambda request: {"status": "ok", "pack": object(),
                         "attempt_log": []}, _base_request())
    assert result["status"] == "failed"
    assert "无法解析" in result["error"]


def test_runner_unknown_result_fields_failed():
    result = run_builder_entrypoint(
        lambda request: {"status": "ok", "pack": None, "extra": 1},
        _base_request())
    assert result["status"] == "failed"
    assert "未知字段" in result["error"]


def test_runner_non_callable_failed():
    result = run_builder_entrypoint("not-callable", _base_request())
    assert result["status"] == "failed"
    assert "不可调用" in result["error"]


def test_runner_ok_with_real_pack(mock_pack, frozen_request):
    """mock 入口真实构建 -> ok 且 pack_hash 可算(mock 通道请求携带
    pack 规范载荷,按载荷确定性重建)。"""
    from rl_curriculum.mock_sealed_exam import mock_build_pack

    result = run_builder_entrypoint(mock_build_pack, frozen_request)
    assert result["status"] == "ok"
    assert result["pack_hash"] == mock_pack.pack_hash()
    assert frozen_request.get("mock_pack_payload") is not None


def test_runner_ok_attempt_loop_without_payload(mock_provider, mock_pack,
                                                duration_contract):
    """无载荷请求(mock 流程的裸构建形态)走完整 attempt 循环。"""
    from rl_curriculum.builder_provenance import (
        build_frozen_build_request,
    )
    from rl_curriculum.mock_sealed_exam import mock_build_pack

    req = build_frozen_build_request(
        mock_provider.builder_identity(), pack=mock_pack,
        duration_contract=duration_contract)
    assert "mock_pack_payload" not in req
    result = run_builder_entrypoint(mock_build_pack, req)
    assert result["status"] == "ok"
    assert result["pack_hash"] == mock_pack.pack_hash()
    assert result["attempt_log"]


def test_frozen_request_derivation(mock_identity, mock_pack,
                                   duration_contract):
    """统一派生:请求字段来自 identity + pack + duration contract。"""
    req = build_frozen_build_request(
        mock_identity, pack=mock_pack,
        duration_contract=duration_contract)
    assert req["builder_manifest_hash"] == mock_identity.manifest_hash
    assert req["timeframe"] == duration_contract["timeframe"]
    assert req["resolved_bars"] == duration_contract["resolved_bars"]
    assert req["pack_name"] == mock_pack.name
    assert frozen_build_request_hash(req).startswith("nbr-")
