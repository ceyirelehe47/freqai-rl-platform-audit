"""阶段 2.6.0d 共享工具:严格 Null 资格链(规范 -> 报告 -> 功效分析)
的确定性磁盘缓存。

三态协议(null-qualification-v4,阶段 2.6.0e)要求每族 >= 64 个独立
seed cluster x 16 episodes 的资格样本(seeds 来自 qualification
namespace 推导);资格链完全确定(seeded 生成器 + seeded bootstrap
+ seeded 功效分析),因此多个测试阶段共享同一份磁盘缓存。

缓存失效通道(fail closed):
- 资格审查代码哈希 nqc-(文件字节)进入缓存键;
- qualification spec 哈希(nqs-)/功效分析代码哈希(npac-)进入键;
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
    qualification_code_hash,
    qualify_null_family,
)
from rl_curriculum.null_qualification_spec import (  # noqa: E402
    build_spec_payload,
    null_qualification_spec_hash,
    qualification_seeds,
)

_STRICT_NULL_FAMILIES = (
    "probe_null_sign", "probe_null_volstate", "probe_null_stochvol",
)
_CACHE_DIR = TESTS_DIR.parent / ".cache" / "null_qual_v3_full"


def _key_material(schema, cfg, params: dict, timeframe: str) -> str:
    from rl_curriculum.null_power_analysis import (
        power_analysis_code_hash,
    )

    return json.dumps({
        "code_hash": qualification_code_hash(),
        "spec_hash": null_qualification_spec_hash(build_spec_payload(
            cfg, timeframe=timeframe,
            episode_bars=int(params["episode_bars"]))),
        "power_code_hash": power_analysis_code_hash(),
        "format": NULL_QUALIFICATION_FORMAT,
        "families": list(_STRICT_NULL_FAMILIES),
        "params": params,
        "cfg": cfg.manifest(),
        "schema": schema.schema_hash(),
        "timeframe": timeframe,
        "seeds": qualification_seeds(MIN_QUALIFICATION_CLUSTERS),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cached_null_qual_chain(
    schema, cfg, *, params=None, timeframe: str = "15m",
) -> dict:
    """返回(必要时生成并缓存)严格 Null 三族的完整资格链:
    {reports, power_report, spec, spec_hash}。

    报告全部必须 QUALIFIED;功效分析 targets_met 必须为真——否则
    直接抛 AssertionError(fail closed,不得把不合格材料送进承诺)。
    """
    from rl_curriculum.null_power_analysis import (
        run_power_analysis,
    )

    qual_params = dict(params) if params is not None else None
    if qual_params is None:
        from rl_curriculum.mock_sealed_exam import BASE_PARAMS

        qual_params = dict(BASE_PARAMS)
    key = hashlib.sha256(
        _key_material(schema, cfg, qual_params, timeframe).encode(
            "utf-8")).hexdigest()
    cache_path = _CACHE_DIR / f"{key}.json"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if (isinstance(cached, dict)
                and set(cached.get("reports") or {}) == set(
                    _STRICT_NULL_FAMILIES)
                and all(
                    isinstance(cached["reports"][f], dict)
                    and cached["reports"][f].get("format")
                    == NULL_QUALIFICATION_FORMAT
                    and set(cached["reports"][f])
                    == set(NULL_REPORT_REQUIRED_KEYS)
                    for f in _STRICT_NULL_FAMILIES)
                and isinstance(cached.get("power_report"), dict)):
            return _validated(cached)

    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    seeds = qualification_seeds(MIN_QUALIFICATION_CLUSTERS)
    # 功效分析需要报告的经验 cluster 分布:先生成报告(引用占位),
    # 功效分析完成后重生成报告填入 power_analysis_ref(引用必须与
    # 承诺绑定的 npa- hash 一致,因此两步生成)
    reports = {
        fam: qualify_null_family(
            DEFAULT_GENERATOR_REGISTRY[fam], params=dict(qual_params),
            timeframe=timeframe, seeds=list(seeds), cfg=cfg,
            schema=schema)
        for fam in _STRICT_NULL_FAMILIES}
    power_report = run_power_analysis(
        reports, margin=build_spec_payload(
            cfg, timeframe=timeframe,
            episode_bars=int(qual_params["episode_bars"])
        )["margin"])
    npa_hash = __import__(
        "rl_curriculum.null_power_analysis", fromlist=["x"]
    ).power_analysis_report_hash(power_report)
    reports = {
        fam: qualify_null_family(
            DEFAULT_GENERATOR_REGISTRY[fam], params=dict(qual_params),
            timeframe=timeframe, seeds=list(seeds), cfg=cfg,
            schema=schema, power_analysis_ref=npa_hash)
        for fam in _STRICT_NULL_FAMILIES}
    out = {
        "reports": reports,
        "power_report": power_report,
        "spec": build_spec_payload(
            cfg, timeframe=timeframe,
            episode_bars=int(qual_params["episode_bars"])),
        "spec_hash": null_qualification_spec_hash(build_spec_payload(
            cfg, timeframe=timeframe,
            episode_bars=int(qual_params["episode_bars"]))),
    }
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(out, sort_keys=True, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return _validated(out)


def _validated(chain: dict) -> dict:
    for fam, rep in chain["reports"].items():
        assert rep["verdict"] == "QUALIFIED", (
            f"{fam} 资格报告未达 QUALIFIED({rep['verdict']}):"
            f"{rep['reasons']}")
        assert rep["power_analysis_ref"] and rep["power_analysis_ref"] \
            .startswith("npa-"), f"{fam} 报告缺功效分析引用"
    assert chain["power_report"]["targets"]["targets_met"] is True, (
        f"功效分析未达标: {chain['power_report']['targets']}")
    return chain


def cached_null_qual_reports(schema, cfg, *, families=None, params=None,
                             timeframe: str = "15m") -> dict[str, dict]:
    """向后兼容:只返回三族报告(完整链经 cached_null_qual_chain)。"""
    return cached_null_qual_chain(
        schema, cfg, params=params, timeframe=timeframe)["reports"]


def null_episode_specs(*, timeframe: str = "15m", attempt: int = 0,
                       families=None):
    """构造每族 32 个 antithetic pair cluster 的 null EpisodeSpec
    列表(BASE_PARAMS;pack 构建	namespace 推导;pair 顺序 seeded
    随机化)——测试自定义 pack 的 null 扩容统一入口。"""
    import numpy as np

    from rl_curriculum.exam_pack import EpisodeSpec
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification_spec import (
        MIN_PACK_CLUSTERS_PER_FAMILY,
        pack_construction_seeds,
        pack_order_seed,
    )

    specs = []
    for fam in (families or ("probe_null_sign", "probe_null_volstate",
                             "probe_null_stochvol")):
        base_seeds = pack_construction_seeds(
            fam, attempt, MIN_PACK_CLUSTERS_PER_FAMILY)
        rng = np.random.default_rng(pack_order_seed(fam, attempt))
        flip_params = dict(BASE_PARAMS)
        flip_params["antithetic_flip"] = True
        for si in rng.permutation(len(base_seeds)):
            specs.append(EpisodeSpec(
                fam, dict(flip_params), int(base_seeds[si]),
                "null_control", timeframe=timeframe))
            specs.append(EpisodeSpec(
                fam, dict(BASE_PARAMS), int(base_seeds[si]),
                "null_control", timeframe=timeframe))
    return specs


def build_commitment_null_materials(pack, schema, cfg, *, chain=None,
                                    registry=None) -> dict:
    """为给定 pack 构建 v4 承诺的全部 Null 材料(测试/实验共用):

    {bindings, power_analysis_report, pack_validity_report}。

    - 家族报告/功效分析来自共享缓存(64 cluster x 16 ep,QUALIFIED,
      targets_met);pack 必须使用 BASE_PARAMS 的 null episodes
      (episode_bars 与资格规范一致);
    - pack_validity_report 对 pack 物化 null episodes 现算
      (每族 >= 32 个 antithetic pair cluster;不达标即抛错,
      构建方应更换 pack seeds)。
    """
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    if chain is None:
        chain = cached_null_qual_chain(schema, cfg)
    from compat_stage2_6_0f import (
        default_duration_contract,
        mock_builder_identity,
    )
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    if registry is None:
        from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY \
            as registry
    null_eps: dict[str, list] = {}
    for spec in pack.episodes:
        if spec.split == "null_control":
            null_eps.setdefault(spec.family, []).append(
                registry[spec.family].generate(
                    dict(spec.params), spec.seed, split=spec.split,
                    timeframe=spec.timeframe))
    contract = default_duration_contract()
    pv_spec = build_spec_for_pack(
        cfg, timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    pv = validate_null_pack(
        null_eps, cfg=cfg, schema=schema, spec=pv_spec,
        pack_hash=pack.pack_hash(),
        builder_identity=mock_builder_identity(),
        duration_contract=contract)
    if pv["verdict"] != "PACK_VALID":
        raise AssertionError(
            f"pack 未通过 pack-level validity: {pv['reasons'][:3]}"
            f"(测试 pack 的 null episodes 必须是每族 32 个 antithetic"
            f" pair cluster,BASE_PARAMS)")
    return {
        "bindings": build_null_qualification_bindings(chain["reports"]),
        "power_analysis_report": chain["power_report"],
        "pack_validity_report": pv,
    }
