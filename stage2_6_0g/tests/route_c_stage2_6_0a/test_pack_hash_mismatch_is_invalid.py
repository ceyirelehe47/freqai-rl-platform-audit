"""工作包 E:pack 哈希不匹配 -> EXAM_INVALID(CLI 级 fail closed)。"""

from __future__ import annotations

import json

from tests.route_c_stage2_6_0a.conftest import run_cli


def test_pack_modification_after_commitment_is_invalid(sealed_exam_env):
    """承诺后修改考试包(换 seed) -> EXAM_INVALID,不接受新哈希。"""
    tmp = sealed_exam_env["tmp"]
    # 篡改 pack:替换 seed
    data = json.loads((tmp / "pack.json").read_text())
    data["episodes"][0]["seed"] = 9999
    (tmp / "pack.json").write_text(json.dumps(data, ensure_ascii=False))
    rc = run_cli(sealed_exam_env, "out.json")
    assert rc == 5
    out = json.loads((tmp / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"
    assert out["result"]["status"] == "EXAM_INVALID"
    assert out["result"]["integrity_ok"] is False


def test_retired_pack_invalid(sealed_exam_env):
    tmp = sealed_exam_env["tmp"]
    rc = run_cli(sealed_exam_env, "out1.json",
                 "--detailed", str(tmp / "detail.json"))
    assert rc == 0
    rc2 = run_cli(sealed_exam_env, "out2.json")
    assert rc2 == 5
    out = json.loads((tmp / "out2.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_integrity_failure_records_no_partial_scores(sealed_exam_env):
    """EXAM_INVALID 不产出部分成绩:无 hard_gates 内容、无分数带。"""
    tmp = sealed_exam_env["tmp"]
    data = json.loads((tmp / "pack.json").read_text())
    data["episodes"][0]["seed"] = 12345
    (tmp / "pack.json").write_text(json.dumps(data, ensure_ascii=False))
    run_cli(sealed_exam_env, "out.json")
    out = json.loads((tmp / "out.json").read_text())
    assert out["result"]["hard_gates"] == {}
    assert out["result"]["score_band"] is None
    assert "report" not in out
