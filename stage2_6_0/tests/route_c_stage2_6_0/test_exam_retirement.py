"""工作包 K:考试包退休机制(详细结果公开后立即退休)。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))


@pytest.fixture()
def pack_and_registry(tmp_path):
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_platform.versions import spec_versions
    from rl_curriculum.probe_charter import audit_probe_charter

    pack = ExamPack(
        name="retire_demo", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(audit_probe_charter()),
        spec_versions=spec_versions(),
        episodes=[EpisodeSpec("probe_segmented_drift", {"episode_bars": 64},
                              s, "train") for s in (1, 2)],
    )
    pack.save(tmp_path / "pack.json")
    return pack, tmp_path


def test_detailed_disclosure_retires_pack(pack_and_registry):
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.exam_pack import RetirementRegistry

    pack, tmp = pack_and_registry
    rc = exam_main([
        "--pack", str(tmp / "pack.json"), "--policy", "rule_trend",
        "--out", str(tmp / "agg.json"),
        "--retire-registry", str(tmp / "ret.json"),
        "--detailed", str(tmp / "detail.json"),
    ])
    assert rc == 0
    assert (tmp / "detail.json").is_file()
    reg = RetirementRegistry(tmp / "ret.json")
    assert reg.is_retired(pack.pack_hash())
    entry = reg.entries()[pack.pack_hash()]
    assert "详细结果已公开" in entry["reason"]


def test_retired_pack_rejected_on_reuse(pack_and_registry):
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.exam_pack import (
        ExamPack,
        RetirementRegistry,
        materialize_pack,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    pack, tmp = pack_and_registry
    exam_main([
        "--pack", str(tmp / "pack.json"), "--policy", "rule_trend",
        "--out", str(tmp / "agg1.json"),
        "--retire-registry", str(tmp / "ret.json"),
        "--detailed", str(tmp / "detail.json"),
    ])
    # 已退休:再评估必须被拒绝
    rc = exam_main([
        "--pack", str(tmp / "pack.json"), "--policy", "rule_trend",
        "--out", str(tmp / "agg2.json"),
        "--retire-registry", str(tmp / "ret.json"),
    ])
    assert rc == 5  # EXAM_INVALID
    out = json.loads((tmp / "agg2.json").read_text())
    assert out["status"] == "EXAM_INVALID"
    assert "退休" in out["error"]
    with pytest.raises(Exception, match="退休"):
        materialize_pack(
            ExamPack.load(tmp / "pack.json"),
            DEFAULT_GENERATOR_REGISTRY,
            retire_registry=RetirementRegistry(tmp / "ret.json"),
        )


def test_aggregate_only_does_not_retire(pack_and_registry):
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.exam_pack import RetirementRegistry

    pack, tmp = pack_and_registry
    exam_main([
        "--pack", str(tmp / "pack.json"), "--policy", "rule_trend",
        "--out", str(tmp / "agg.json"),
        "--retire-registry", str(tmp / "ret.json"),
    ])
    assert not RetirementRegistry(tmp / "ret.json").is_retired(
        pack.pack_hash())
