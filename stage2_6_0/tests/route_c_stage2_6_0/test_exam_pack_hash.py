"""工作包 K:考试包哈希稳定性与内容校验 fail closed。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.charter import charter_hash
from rl_curriculum.exam_pack import (
    ExamPack,
    ExamPackError,
    EpisodeSpec,
    RetirementRegistry,
    materialize_pack,
)
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.probe_charter import audit_probe_charter

CH = charter_hash(audit_probe_charter())


def _pack():
    return ExamPack(
        name="t", version="v1", visibility="mock_hidden", charter_hash=CH,
        spec_versions={"env_core_version": "RouteCEnvCore-v1.0.0"},
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 1,
                        "train"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 2,
                        "dev_seed_holdout"),
        ],
    )


def test_pack_hash_stable_across_construction_and_io(tmp_path):
    p = _pack()
    h1 = p.pack_hash()
    p.save(tmp_path / "pack.json")
    p2 = ExamPack.load(tmp_path / "pack.json")
    assert p2.pack_hash() == h1
    # created_utc 不同不影响内容哈希
    p3 = _pack()
    p3.created_utc = "1999-01-01T00:00:00+00:00"
    assert p3.pack_hash() == h1


def test_pack_hash_changes_on_content_change():
    base = _pack().pack_hash()
    p = _pack()
    p.episodes.append(
        EpisodeSpec("probe_null_control", {}, 9, "null_control"))
    assert p.pack_hash() != base
    p2 = _pack()
    p2.charter_hash = "c-other"
    assert p2.pack_hash() != base


def test_episode_order_does_not_change_hash():
    p = _pack()
    p.episodes.reverse()
    assert p.pack_hash() == _pack().pack_hash()


def test_bad_schema_rejected(tmp_path):
    bad = {"schema": "other-v0", "name": "t", "version": "v",
           "visibility": "public", "charter_hash": CH,
           "spec_versions": {}, "episodes": []}
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(ExamPackError, match="schema"):
        ExamPack.load(tmp_path / "bad.json")


def test_missing_pack_file_rejected(tmp_path):
    with pytest.raises(ExamPackError, match="不存在"):
        ExamPack.load(tmp_path / "nope.json")


def test_unknown_visibility_rejected():
    with pytest.raises(ExamPackError):
        ExamPack(name="t", version="v", visibility="secret",
                 charter_hash=CH, spec_versions={}, episodes=[
                     EpisodeSpec("probe_segmented_drift", {}, 1, "train")])


def test_materialize_unknown_family_rejected(tmp_path):
    p = ExamPack(
        name="t", version="v", visibility="public", charter_hash=CH,
        spec_versions={},
        episodes=[EpisodeSpec("mystery_family", {}, 1, "train")])
    with pytest.raises(ExamPackError, match="未注册生成器族"):
        materialize_pack(p, DEFAULT_GENERATOR_REGISTRY)


def test_materialize_sorted_deterministic():
    p = _pack()
    p.episodes.reverse()
    eps = materialize_pack(p, DEFAULT_GENERATOR_REGISTRY)
    specs = [e.spec.canonical() for e in eps]
    assert specs == sorted(specs)
