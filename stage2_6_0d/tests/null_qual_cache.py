"""阶段 2.6.0d 共享工具:严格 Null 资格报告的确定性磁盘缓存。

三态协议(null-qualification-v3)要求每族 >= 64 个独立 seed cluster
x 8 episodes 的资格样本(首次生成约半分钟);资格报告完全确定
(seeded 生成器 + seeded bootstrap),因此多个测试阶段的 conftest
共享同一份磁盘缓存。

缓存失效通道(fail closed):
- 资格审查代码哈希 nqc-(文件字节)进入缓存键——null_qualification.py
  任何修改自动重建缓存;
- 生成器 params / EvalConfig manifest / Observation Schema hash /
  timeframe / seed 列表全部进入缓存键;
- 命中后仍校验 format 与报告键集合,不匹配即重建。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rl_curriculum.null_qualification import (  # noqa: E402
    MIN_QUALIFICATION_CLUSTERS,
    NULL_QUALIFICATION_FORMAT,
    NULL_REPORT_REQUIRED_KEYS,
    DEFAULT_EPISODES_PER_SEED,
    qualification_code_hash,
)

#: mock/测试链路统一使用的资格 seed(64 个独立 cluster,预注册)
DEFAULT_QUALIFICATION_SEEDS: list[int] = list(range(11, 75))

_STRICT_NULL_FAMILIES = (
    "probe_null_sign", "probe_null_volstate", "probe_null_stochvol",
)
_CACHE_DIR = TESTS_DIR.parent / ".cache" / "null_qual_v3"


def cached_null_qual_reports(
    schema, cfg, *, families=None, params=None, timeframe: str = "15m",
) -> dict[str, dict]:
    """返回(必要时生成并缓存)严格 Null 三族的 v3 资格报告。

    返回值必须全部为 QUALIFIED——调用方(mock 承诺链路)依赖这一点;
    若某族未 QUALIFIED(代码/参数回归),直接抛 AssertionError
    (fail closed,不得把 INSUFFICIENT/INVALID 报告送进承诺)。
    """
    from rl_curriculum.null_qualification import qualify_null_family

    fams = tuple(families or _STRICT_NULL_FAMILIES)
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    qual_params = dict(params or BASE_PARAMS)
    key_material = json.dumps({
        "code_hash": qualification_code_hash(),
        "format": NULL_QUALIFICATION_FORMAT,
        "families": list(fams),
        "params": qual_params,
        "cfg": cfg.manifest(),
        "schema": schema.schema_hash(),
        "timeframe": timeframe,
        "seeds": DEFAULT_QUALIFICATION_SEEDS,
        "episodes_per_seed": DEFAULT_EPISODES_PER_SEED,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    cache_path = _CACHE_DIR / f"{key}.json"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if (isinstance(cached, dict)
                and set(cached) == set(fams)
                and all(
                    isinstance(cached[f], dict)
                    and cached[f].get("format") == NULL_QUALIFICATION_FORMAT
                    and set(cached[f]) == set(NULL_REPORT_REQUIRED_KEYS)
                    for f in fams)):
            _assert_all_qualified(cached)
            return cached

    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    reports: dict[str, dict] = {}
    for fam in fams:
        reports[fam] = qualify_null_family(
            DEFAULT_GENERATOR_REGISTRY[fam], params=dict(qual_params),
            timeframe=timeframe, seeds=list(DEFAULT_QUALIFICATION_SEEDS),
            cfg=cfg, schema=schema)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(reports, sort_keys=True, ensure_ascii=False, indent=1),
        encoding="utf-8")
    _assert_all_qualified(reports)
    return reports


def _assert_all_qualified(reports: dict[str, dict]) -> None:
    for fam, rep in reports.items():
        assert rep["verdict"] == "QUALIFIED", (
            f"{fam} 资格报告未达 QUALIFIED({rep['verdict']}):"
            f"{rep['reasons']}(缓存种子 {DEFAULT_QUALIFICATION_SEEDS[0]}"
            f"..{DEFAULT_QUALIFICATION_SEEDS[-1]} 共 "
            f"{MIN_QUALIFICATION_CLUSTERS} cluster)")
