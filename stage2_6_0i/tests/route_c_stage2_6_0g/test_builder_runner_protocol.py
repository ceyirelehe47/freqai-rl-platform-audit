"""阶段 2.6.0g 收尾:builder-build-request-v3 / result-v2 / attempt log
合同的精确字段校验(工作包 C/D)。

- request:mode 驱动的精确白名单(未知字段/缺失字段/路径值/候选字段
  一律拒绝;不再只有候选字段黑名单);
- mode 协议:builder_execution 携带 mock_pack_payload 一律拒绝(D2
  硬闸);mock_payload_assembly 必须携带载荷且与 mode 自洽;
- result:精确字段集合 + format/protocol 强制(D3,经 Runner 侧
  校验器在干净子进程验证);
- attempt log:规范化合同(序号/上限/每次结果/匿名拒绝原因/最终选中
  /输出 pack hash;不得只记录条目数量;D4)。
"""

from __future__ import annotations

import copy
import json

import pytest


def _base_request(frozen_request):
    """从 mock 冻结请求构造 builder_execution 私有请求基线。"""
    req = copy.deepcopy(frozen_request)
    req.pop("mock_pack_payload", None)
    req["mode"] = "builder_execution"
    req["format"] = "builder-build-request-v3"
    req["runner_protocol"] = "builder-runner-protocol-v3"
    req["attempt_policy"] = {"policy": "first_pass",
                             "max_attempts": int(req["max_attempts"])}
    return req


def test_mock_request_passes_whitelist(frozen_request):
    from rl_curriculum.builder_provenance import (
        check_frozen_build_request,
    )

    check_frozen_build_request(frozen_request)
    assert frozen_request["mode"] == "mock_payload_assembly"
    assert isinstance(frozen_request["mock_pack_payload"], dict)


def test_private_request_passes_whitelist(frozen_request):
    from rl_curriculum.builder_provenance import (
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    check_frozen_build_request(req)
    assert "mock_pack_payload" not in req


def test_unknown_field_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["secret_extension"] = {"anything": 1}
    with pytest.raises(BuilderProvenanceError, match="未注册字段"):
        check_frozen_build_request(req)


def test_missing_field_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req.pop("params_spec")
    with pytest.raises(BuilderProvenanceError, match="缺少必填字段"):
        check_frozen_build_request(req)


def test_request_with_candidate_field_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["params_spec"] = {"candidate_score": 0.9}
    with pytest.raises(BuilderProvenanceError,
                       match="candidate_score|禁止字段"):
        check_frozen_build_request(req)


def test_request_with_nested_checkpoint_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["families"] = ["probe_null_sign", {"checkpoint_path": "/x/y"}]
    with pytest.raises(BuilderProvenanceError,
                       match="禁止字段|路径值"):
        check_frozen_build_request(req)


def test_request_with_path_value_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["pack_name"] = "/etc/passwd"
    with pytest.raises(BuilderProvenanceError, match="路径值"):
        check_frozen_build_request(req)


def test_request_with_relative_path_value_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["params_spec"] = {"data_file": "hidden/pack.json"}
    with pytest.raises(BuilderProvenanceError, match="路径值"):
        check_frozen_build_request(req)


def test_mode_missing_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req.pop("mode")
    with pytest.raises(BuilderProvenanceError, match="mode"):
        check_frozen_build_request(req)


def test_mode_unknown_rejected(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["mode"] = "hybrid_escape"
    with pytest.raises(BuilderProvenanceError, match="mode"):
        check_frozen_build_request(req)


def test_private_mode_with_payload_rejected(frozen_request):
    """D2 硬闸:builder_execution 请求携带 mock_pack_payload 一律拒绝。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = _base_request(frozen_request)
    req["mock_pack_payload"] = dict(frozen_request["mock_pack_payload"])
    with pytest.raises(BuilderProvenanceError, match="mock_pack_payload"):
        check_frozen_build_request(req)


def test_private_mode_with_payload_rejected_at_derivation(frozen_request):
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        build_frozen_build_request,
    )

    class _I:
        manifest = {"families": ["f"], "pair_count_per_family": 1,
                    "max_attempts": 1, "params_spec": {}}
        manifest_hash = "npb-x"
        builder_protocol = "null-pack-builder-protocol-v3"

    class _P:
        name = "p"
        version = "v"
        timeframe = "15m"

        def to_json(self):
            return json.dumps(frozen_request["mock_pack_payload"])

    with pytest.raises(BuilderProvenanceError):
        build_frozen_build_request(
            _I(), pack=_P(),
            duration_contract={"timeframe": "15m", "resolved_bars": 96,
                               "resolved_duration_hours": 24.0,
                               "format": "null-duration-contract-v1"},
            mode="builder_execution",
            include_mock_pack_payload=True)


def test_mock_mode_without_payload_rejected(frozen_request):
    """mock_payload_assembly 请求必须携带载荷(mode 与载荷自洽)。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_frozen_build_request,
    )

    req = copy.deepcopy(frozen_request)
    req.pop("mock_pack_payload")
    with pytest.raises(BuilderProvenanceError, match="mock_pack_payload"):
        check_frozen_build_request(req)


def test_request_hash_stable(frozen_request):
    from rl_curriculum.builder_provenance import (
        frozen_build_request_hash,
    )

    h1 = frozen_build_request_hash(frozen_request)
    h2 = frozen_build_request_hash(copy.deepcopy(frozen_request))
    assert h1 == h2 and h1.startswith("nbr-")


# ------------------------------------------------------------ result 合同
def test_result_contract_fields_enforced():
    """Runner 侧 result 白名单/format/protocol 强制(D3,干净子进程)。"""
    import subprocess
    import sys as _sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(src)!r})\n"
        "from rl_builder_runtime.runner import _validate_build_result\n"
        "cases = [\n"
        "    ('missing-format', lambda r: r.pop('format')),\n"
        "    ('wrong-format', lambda r: r.update(format='builder-build-result-v1')),\n"
        "    ('missing-protocol', lambda r: r.pop('runner_protocol')),\n"
        "    ('wrong-protocol', lambda r: r.update(runner_protocol='builder-runner-protocol-v1')),\n"
        "    ('unknown-field', lambda r: r.update(extra=1)),\n"
        "    ('status-failed', lambda r: r.update(status='failed')),\n"
        "    ('pack-none', lambda r: r.update(pack=None)),\n"
        "    ('error-nonnull', lambda r: r.update(error='x')),\n"
        "]\n"
        "out = {}\n"
        "for name, mutate in cases:\n"
        "    r = {'format': 'builder-build-result-v3',\n"
        "         'runner_protocol': 'builder-runner-protocol-v3',\n"
        "         'status': 'ok', 'pack': {'schema': 'exam-pack-v1'},\n"
        "         'attempt_log': {'format': 'builder-attempt-log-v2',\n"
        "                         'max_attempts': 0, 'attempts': [],\n"
        "                         'selected_attempt': None}, 'error': None}\n"
        "    mutate(r)\n"
        "    try:\n"
        "        _validate_build_result(\n"
        "            r, attempt_policy={'policy': 'assembly',\n"
        "                               'max_attempts': 0})\n"
        "        out[name] = 'ACCEPTED'\n"
        "    except Exception as exc:\n"
        "        out[name] = type(exc).__name__\n"
        "print(json.dumps(out))\n"
    )
    proc = subprocess.run([_sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=120)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    for name, verdict in out.items():
        assert verdict == "_RunnerFailure", f"{name} 未被拒绝: {verdict}"


def test_assembly_mode_result_without_attempts_ok():
    """组装模式 result(max_attempts=0 无 attempt 条目)合法。"""
    import subprocess
    import sys as _sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(src)!r})\n"
        "from rl_builder_runtime.runner import _validate_build_result\n"
        "r = {'format': 'builder-build-result-v3',\n"
        "     'runner_protocol': 'builder-runner-protocol-v3',\n"
        "     'status': 'ok', 'pack': {'schema': 'exam-pack-v1'},\n"
        "     'attempt_log': {'format': 'builder-attempt-log-v2',\n"
        "                     'max_attempts': 0, 'attempts': [],\n"
        "                     'selected_attempt': None}, 'error': None}\n"
        "_validate_build_result(\n"
"    r, attempt_policy={'policy': 'assembly', 'max_attempts': 0})\n"
        "print('OK')\n"
    )
    proc = subprocess.run([_sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=120)
    assert "OK" in proc.stdout


# ------------------------------------------------------------ attempt log
def _log(**over):
    log = {
        "format": "builder-attempt-log-v2",
        "max_attempts": 5,
        "attempts": [
            {"attempt": 0, "verdict": "reject",
             "reject_reasons": ["center-above-bound"]},
            {"attempt": 1, "verdict": "accept", "reject_reasons": []},
        ],
        "selected_attempt": 1,
        "output_pack_hash": "p-" + "a" * 64,
    }
    log.update(over)
    return log


def test_attempt_log_contract_ok():
    from rl_curriculum.builder_provenance import (
        attempt_log_hash, check_attempt_log,
    )

    check_attempt_log(_log(), max_attempts=5)
    assert attempt_log_hash(_log()).startswith("nal-")


def test_attempt_log_wrong_format_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    log = _log(format="builder-attempt-log-v0")
    with pytest.raises(BuilderProvenanceError, match="format"):
        check_attempt_log(log)


def test_attempt_log_extra_field_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    log = _log()
    log["count_only"] = 2
    with pytest.raises(BuilderProvenanceError, match="字段集合"):
        check_attempt_log(log)


def test_attempt_log_reject_without_reasons_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    log = _log(attempts=[
        {"attempt": 0, "verdict": "reject", "reject_reasons": []},
        {"attempt": 1, "verdict": "accept", "reject_reasons": []},
    ])
    with pytest.raises(BuilderProvenanceError, match="匿名拒绝原因"):
        check_attempt_log(log)


def test_attempt_log_accept_with_reasons_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    log = _log(attempts=[
        {"attempt": 0, "verdict": "accept",
         "reject_reasons": ["spurious"]},
    ], selected_attempt=0)
    with pytest.raises(BuilderProvenanceError, match="不自洽"):
        check_attempt_log(log)


def test_attempt_log_selected_must_be_accept():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    log = _log(selected_attempt=0)
    with pytest.raises(BuilderProvenanceError, match="accept|选中"):
        check_attempt_log(log)


def test_attempt_log_selected_missing_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    log = _log(selected_attempt=None)
    with pytest.raises(BuilderProvenanceError, match="accept|选中"):
        check_attempt_log(log)


def test_attempt_log_entry_count_over_max_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    entries = [{"attempt": i, "verdict": "reject",
                "reject_reasons": ["r"]} for i in range(6)]
    log = _log(attempts=entries)
    with pytest.raises(BuilderProvenanceError, match="max_attempts"):
        check_attempt_log(log)


def test_attempt_log_max_attempts_drift_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_attempt_log,
    )

    with pytest.raises(BuilderProvenanceError, match="漂移"):
        check_attempt_log(_log(), max_attempts=8)


def test_canonicalize_fills_output_pack_hash():
    from rl_curriculum.builder_provenance import (
        canonicalize_attempt_log,
    )

    raw = {
        "format": "builder-attempt-log-v2",
        "max_attempts": 5,
        "attempts": [
            {"attempt": 0, "verdict": "reject",
             "reject_reasons": ["center-above-bound"]},
            {"attempt": 1, "verdict": "accept", "reject_reasons": []},
        ],
        "selected_attempt": 1,
    }
    log = canonicalize_attempt_log(
        raw, output_pack_hash="p-" + "b" * 64, max_attempts=5)
    assert log["output_pack_hash"] == "p-" + "b" * 64
