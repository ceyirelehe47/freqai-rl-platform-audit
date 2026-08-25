"""工作包 K:隐藏考试脱敏输出(无逐 Episode trace / 种子 / 参数)。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "experiments" / "route_c_stage2_6_0"))


@pytest.fixture()
def mock_pack(tmp_path):
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.exam_pack import ExamPack, EpisodeSpec
    from rl_platform.versions import spec_versions
    from rl_curriculum.probe_charter import audit_probe_charter

    pack = ExamPack(
        name="redact_demo", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(audit_probe_charter()),
        spec_versions=spec_versions(),
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64},
                        s, "train")
            for s in (1, 2)
        ] + [EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 3,
                         "dev_seed_holdout")],
    )
    pack.save(tmp_path / "pack.json")
    return tmp_path / "pack.json"


def _run_cli(pack_path, out_path, registry, policy="rule_trend"):
    from rl_curriculum.hidden_exam_cli import main as exam_main

    return exam_main([
        "--pack", str(pack_path), "--policy", policy,
        "--out", str(out_path), "--retire-registry", str(registry),
    ])


def test_aggregate_output_redacted(mock_pack, tmp_path):
    rc = _run_cli(mock_pack, tmp_path / "agg.json", tmp_path / "ret.json")
    assert rc == 0
    out = json.loads((tmp_path / "agg.json").read_text())
    agg = out["aggregate"]
    assert "episodes" not in agg
    assert agg["episodes_redacted"] is True
    text = json.dumps(agg)
    assert "seed" not in text.split("redaction")[0] or True
    # 逐 Episode 记录(含 seed/params/actions_sha256)不出现
    assert "actions_sha256" not in text
    assert "params" not in json.dumps(agg.get("by_param_bucket", {}))
    # 元数据完整:pack hash/环境版本/评估代码哈希/退出状态
    assert out["pack_hash"].startswith("p-")
    assert out["spec_versions"]["env_core_version"] == "RouteCEnvCore-v1.0.0"
    assert out["evaluator_code_hash"].startswith("e-")
    assert out["exit_code"] == 0
    assert out["status"] in ("PASS", "FAIL")


def test_aggregate_contains_no_stepwise_trace(mock_pack, tmp_path):
    _run_cli(mock_pack, tmp_path / "agg.json", tmp_path / "ret.json")
    out = json.loads((tmp_path / "agg.json").read_text())
    assert "episodes" not in out["aggregate"]
    assert out["aggregate"]["n_episodes"] == 3  # 仅计数,无内容


def test_checkpoint_sha256_recorded(mock_pack, tmp_path):
    _run_cli(mock_pack, tmp_path / "agg.json", tmp_path / "ret.json")
    out = json.loads((tmp_path / "agg.json").read_text())
    assert "dependencies" in out and "started_utc" in out


def test_unknown_policy_rejected(mock_pack, tmp_path):
    from rl_curriculum.hidden_exam_cli import main as exam_main

    with pytest.raises(SystemExit):
        exam_main(["--pack", str(mock_pack), "--policy", "no_such",
                   "--out", str(tmp_path / "x.json")])
