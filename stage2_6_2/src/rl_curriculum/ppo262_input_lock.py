"""阶段 2.6.2:输入锁(Stage 2.6.1 R2 只读输入的绑定与验证)。

训练开始前必须全部通过(§7);任何不一致 -> 立即停止:

1. R2 qualification verdict = PASS;
2. R2 plan digest 复算一致(qp-8f64a1b5...,绑定 result 与 exposure);
3. R2 exposure status = completed(语料已消耗,2.6.2 不得触碰);
4. C1/C2/C3 family versions 与 plan 一致(generator 只读);
5. 2.6.1 课程源码 tree 未被本阶段修改(code_identity 逐文件重算);
6. production observation identity 未漂移(schema hash / 8 特征列 /
   RouteCStrategy 双 sha256 / observation_dim=9);
7. preprocessing boundary 未漂移(causal unscaled 边界 artifact);
8. Route C 冻结合同未漂移(rl_platform tree hash 重算);
9. Freqtrade vendor pin 未漂移(52bc96f...)且 clean。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
from rl_curriculum.curriculum261_plan import load_locked_plan
from rl_curriculum.curriculum261_production_obs import (
    production_observation_identity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
R2_EXPECTED_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99"
)
PPO262_EXPECTED_VENDOR_SHA = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"

#: Stage 2.6.1 Repair R3 迭代登记的 2.6.1 源码变更(显式白名单):
#: R3 于 baseline 1b47db4 之后修改了 curriculum261_api.py(R3 seed
#: namespace 白名单扩展 + qualification_r3 完整 lock 守卫 + 删除被
#: 覆盖的重复 _derive261_seed_raw 死代码)。该修改不改变 R2 corpus
#: 的 seed 派生(_derive261_seed_raw 生效实现与 R2 版本逐字节同逻辑,
#: 回归测试锁定)与 generator/family/production obs 语义。守卫语义:
#: 登记文件必须精确等于登记哈希(再漂移即 fail);未登记文件的任何
#: 漂移仍然 fail。
R3_REGISTERED_CODE_CHANGES = {
    "curriculum261_api.py":
        "31d6f6fbaf2f438654c34bbce63b9c33888997e4cdf655337d6f5a5cf500d636",
}

#: Stage 2.6.1 Repair R4 迭代登记(显式白名单,同一守卫语义):
#: R4 于 baseline d105405 之后再次修改 curriculum261_api.py —— 仅
#: 扩展 R4 seed namespace 白名单(CURRICULUM261_R4_NAMESPACES 追加
#: 进 CURRICULUM261_SEED_NAMESPACES)+ qualification_r4 /
#: preprocess_fit_qualification_r4 的完整 lock 守卫(沿 R3 §32 四要
#: 素并加 parameter pack 绑定)。_derive261_seed_raw 的 payload 构造
#: 与历史逐字节同构(黄金向量锁定),R2/R3 corpus seed 派生不变;
#: generator/family/production obs 语义不变。登记哈希 = R4 版
#: curriculum261_api.py 的精确 sha256(覆盖 R3 登记值,即登记表按
#: "当前树实际内容"守卫;再漂移仍 fail)。
R4_REGISTERED_CODE_CHANGES = {
    "curriculum261_api.py":
        "2286c2db941c9642088b3779477f52596ddb18d2ac63c6cd39ae71aebe58a46e",
}

#: 全部迭代登记的合并视图(R4 覆盖同名键;run_input_lock 的守卫
#: 数据源;artifact 键名沿用 registered_r3_iteration_changes 以保持
#: 2.6.2 测试契约稳定,语义为"迭代登记变更全集")。
REGISTERED_261_CODE_CHANGES = {
    **R3_REGISTERED_CODE_CHANGES, **R4_REGISTERED_CODE_CHANGES}
VENDOR_DIR = PROJECT_ROOT / "vendor" / "freqtrade"
RL_PLATFORM_DIR = PROJECT_ROOT / "src" / "rl_platform"
#: 2.6.1 code_identity 的模块清单(plan.code_identity 的键即合同)
CURRICULUM_MODULES_DIR = PROJECT_ROOT / "src" / "rl_curriculum"


def r2_artifacts_dir() -> Path:
    return qualification_r2_lock_marker().parent


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _tree_hash(root: Path) -> str:
    """rl_platform 源码树哈希(2.6.1 final.py 同款算法:键=文件名)。"""
    files: dict[str, str] = {}
    for f in sorted(root.rglob("*.py")):
        files[f.name] = _sha256_file(f)
    return "rp-" + hashlib.sha256(
        json.dumps(files, sort_keys=True).encode()).hexdigest()


def vendor_status() -> dict[str, Any]:
    """vendor pin 状态(sha + porcelain clean)。"""
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(VENDOR_DIR),
        capture_output=True, text=True).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(VENDOR_DIR),
        capture_output=True, text=True).stdout.strip()
    return {
        "vendor_path": str(VENDOR_DIR),
        "sha": sha,
        "clean": porcelain == "",
        "status_porcelain": porcelain[:500],
    }


def run_input_lock() -> dict[str, Any]:
    """执行全部输入锁检查,返回结构化 artifact(输入锁汇总)。"""
    problems: list[str] = []
    checks: dict[str, bool] = {}

    plan_dir = r2_artifacts_dir()
    result_path = plan_dir / "qualification_result.json"
    exposure_path = plan_dir / "qualification_exposure_r2.json"
    for p in (plan_dir / "qualification_plan.json", result_path,
              exposure_path):
        if not p.is_file():
            problems.append(f"R2 artifact 缺失: {p.name}")
    if problems:
        return {"format": "ppo262-input-lock-v1", "pass": False,
                "problems": problems, "checks": {}}

    # 1-2. plan digest 复算 + result/exposure 绑定
    plan, digest = load_locked_plan(plan_dir)  # 内部已复算,篡改即抛错
    checks["plan_digest_recomputed"] = digest == R2_EXPECTED_PLAN_DIGEST
    if not checks["plan_digest_recomputed"]:
        problems.append(
            f"R2 plan digest 复算 {digest} != 期望 {R2_EXPECTED_PLAN_DIGEST}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    exposure = json.loads(exposure_path.read_text(encoding="utf-8"))

    # 1. verdict
    checks["r2_verdict_pass"] = result.get("verdict") == "PASS"
    if not checks["r2_verdict_pass"]:
        problems.append(f"R2 verdict = {result.get('verdict')!r} != PASS")

    # 2. result/exposure 绑定同一 digest
    checks["result_binds_plan"] = result.get("plan_digest") == digest
    checks["exposure_binds_plan"] = exposure.get("plan_digest") == digest
    if not checks["result_binds_plan"]:
        problems.append("qualification_result 未绑定 plan digest")
    if not checks["exposure_binds_plan"]:
        problems.append("exposure marker 未绑定 plan digest")

    # 3. exposure completed
    checks["r2_exposure_completed"] = exposure.get("status") == "completed"
    if not checks["r2_exposure_completed"]:
        problems.append(
            f"R2 exposure status = {exposure.get('status')!r} != completed")

    # 4. family versions:现场 generator(只读复用)与 plan 一致,
    #    且 R2 corpus 记录(curriculum_family_summary)同版本同参数
    from rl_curriculum.curriculum261_pairs import family_specs
    specs = family_specs()
    fam_versions: dict[str, str] = {
        fam: plan["families"][fam]["family_version"]
        for fam in plan["families"]}
    live_versions = {
        fam: spec.generator.family_version for fam, spec in specs.items()}
    summary_path = plan_dir / "curriculum_family_summary.json"
    summary_ok = True
    summary_detail: dict[str, Any] = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for fam, fam_plan in plan["families"].items():
            rec = summary.get(fam, {})
            if rec.get("family_version") != fam_plan["family_version"]:
                summary_ok = False
            summary_detail[fam] = rec.get("family_version")
            if rec.get("rung_params") != fam_plan["rung_params"]:
                summary_ok = False
                summary_detail[f"{fam}:rung_params"] = "mismatch"
    else:
        summary_ok = False
    checks["family_versions_consistent"] = (
        live_versions == fam_versions and summary_ok)
    if live_versions != fam_versions:
        problems.append(
            f"generator family versions 漂移: plan={fam_versions} "
            f"live={live_versions}")
    if not summary_ok:
        problems.append(
            "R2 curriculum_family_summary 与 plan 的 family_version/"
            "rung_params 不一致")

    # 5. 2.6.1 课程源码未被修改(code_identity 逐文件重算;
    #    函数级键 RouteCStrategy.feature_engineering_standard 取
    #    production_observation_identity() 的对应字段)
    code_identity = plan["code_identity"]
    identity_for_code = production_observation_identity()
    module_hashes: dict[str, str] = {}
    code_drift: dict[str, dict[str, str]] = {}
    for fname, expected in code_identity.items():
        if fname == "RouteCStrategy.feature_engineering_standard":
            actual = identity_for_code["feature_engineering_standard_sha256"]
        elif fname.startswith("RouteCStrategy"):
            fpath = (PROJECT_ROOT / "user_data" / "strategies"
                     / "RouteCStrategy.py")
            actual = _sha256_file(fpath)
        else:
            fpath = CURRICULUM_MODULES_DIR / fname
            actual = _sha256_file(fpath)
        module_hashes[fname] = actual
        if actual != expected:
            code_drift[fname] = {"expected": expected, "actual": actual}
    # 迭代登记变更(R3/R4 显式白名单):登记文件漂移到精确登记值视为
    # 合法迭代变更;任何未登记漂移(含登记文件的再漂移)仍 fail closed。
    registered_ok: dict[str, bool] = {}
    for fname in list(code_drift):
        registered = REGISTERED_261_CODE_CHANGES.get(fname)
        if registered is not None and code_drift[fname]["actual"] == registered:
            registered_ok[fname] = True
            del code_drift[fname]
    checks["stage261_source_unchanged"] = not code_drift
    checks["stage261_registered_r3_changes_valid"] = all(
        registered_ok.values())
    if code_drift:
        problems.append(f"2.6.1 源码漂移(未登记): {sorted(code_drift)}")

    # 6. production observation identity 未漂移(现场重算 vs R2 记录)
    identity_now = production_observation_identity()
    identity_r2 = json.loads(
        (plan_dir / "production_observation_identity.json").read_text(
            encoding="utf-8"))
    identity_keys = ("schema_hash", "feature_columns", "observation_dim",
                     "window_size", "strategy_file_sha256",
                     "feature_engineering_standard_sha256",
                     "env_core_version", "observation_spec_version")
    identity_drift = {
        k: {"r2": identity_r2.get(k), "now": identity_now.get(k)}
        for k in identity_keys
        if json.dumps(identity_r2.get(k), sort_keys=True) != json.dumps(
            identity_now.get(k), sort_keys=True)
    }
    checks["production_obs_identity_unchanged"] = not identity_drift
    if identity_drift:
        problems.append(f"production observation identity 漂移: "
                        f"{sorted(identity_drift)}")

    # 7. preprocessing boundary 未漂移(boundary artifact 重生成对比)
    boundary_now = _preprocessing_boundary_now()
    boundary_r2 = json.loads(
        (plan_dir / "production_preprocessing_boundary.json").read_text(
            encoding="utf-8"))
    boundary_drift = {
        k: {"r2": boundary_r2.get(k), "now": boundary_now.get(k)}
        for k in ("boundary_name",)
        if json.dumps(boundary_r2.get(k), sort_keys=True) != json.dumps(
            boundary_now.get(k), sort_keys=True)
    }
    if "causal unscaled" not in boundary_r2.get(
            "components", {}).get("feature_values", ""):
        boundary_drift["feature_values"] = {
            "r2": boundary_r2.get("components", {}).get("feature_values"),
            "now": "causal unscaled 口径缺失"}
    checks["preprocessing_boundary_unchanged"] = not boundary_drift
    if boundary_drift:
        problems.append(f"preprocessing boundary 漂移: {sorted(boundary_drift)}")

    # 8. Route C 冻结合同未漂移(rl_platform tree hash)
    tree_now = _tree_hash(RL_PLATFORM_DIR)
    frozen_r2 = json.loads(
        (plan_dir / "frozen_contract_integrity.json").read_text(
            encoding="utf-8"))
    tree_r2 = frozen_r2["rl_platform_tree_hash"]
    checks["route_c_tree_hash_unchanged"] = tree_now == tree_r2
    if tree_now != tree_r2:
        problems.append(
            f"rl_platform tree hash 漂移: r2={tree_r2} now={tree_now}")
    versions_now = _route_c_versions_now()
    checks["route_c_frozen_versions_unchanged"] = (
        versions_now == frozen_r2["expected"])
    if versions_now != frozen_r2["expected"]:
        problems.append(f"Route C 冻结版本漂移: {versions_now}")

    # 9. vendor pin
    vs = vendor_status()
    checks["vendor_pin_unchanged"] = vs["sha"] == PPO262_EXPECTED_VENDOR_SHA
    checks["vendor_clean"] = vs["clean"]
    if not checks["vendor_pin_unchanged"]:
        problems.append(f"vendor pin 漂移: {vs['sha']}")
    if not checks["vendor_clean"]:
        problems.append("vendor 工作树不 clean")

    artifact = {
        "format": "ppo262-input-lock-v1",
        "stage": "stage2_6_2",
        "r2_plan_digest": digest,
        "r2_verdict": result.get("verdict"),
        "r2_exposure_status": exposure.get("status"),
        "family_versions": fam_versions,
        "checks": checks,
        "curriculum_source_identity": {
            "r2_code_identity": code_identity,
            "recomputed": module_hashes,
            "recomputed_minus_registered_r3": {
                k: v for k, v in module_hashes.items()
                if k not in REGISTERED_261_CODE_CHANGES},
            "registered_r3_iteration_changes": REGISTERED_261_CODE_CHANGES,
            "r3_change_note": "R3/R4 迭代合法变更(见模块 docstring 与"
                              "各轮 governance_waiver;键名沿用 R3 历"
                              "史,语义=迭代登记变更全集);R2 seed"
                              "派生与 generator 语义不变",
        },
        "rl_platform_tree_hash": {"r2": tree_r2, "now": tree_now},
        "route_c_frozen_versions": versions_now,
        "vendor": vs,
        "problems": problems,
        "pass": not problems and all(checks.values()),
    }
    return artifact


def _route_c_versions_now() -> dict[str, str]:
    from rl_platform.versions import (
        ACTION_SPEC_VERSION, ENV_CORE_VERSION, EXECUTION_CONTRACT_VERSION,
        OBSERVATION_SPEC_VERSION, REWARD_SPEC_VERSION,
        TERMINAL_LIQUIDATION_VERSION,
    )

    return {
        "env_core": ENV_CORE_VERSION,
        "observation_spec": OBSERVATION_SPEC_VERSION,
        "action_spec": ACTION_SPEC_VERSION,
        "reward_spec": REWARD_SPEC_VERSION,
        "execution": EXECUTION_CONTRACT_VERSION,
        "terminal_liquidation": TERMINAL_LIQUIDATION_VERSION,
    }


def _preprocessing_boundary_now() -> dict[str, Any]:
    """preprocessing boundary 语义口径(2.6.2 与 R2 同一 adapter)。

    2.6.1 未暴露独立构造函数;boundary 的数值面(特征语义/layout/
    causal unscaled)由 production observation identity 检查承载,
    这里显式断言口径字符串与 R2 artifact 的 boundary_name 一致。
    """
    return {
        "boundary_name": (
            "real RouteCStrategy feature semantics + frozen Route C "
            "observation layout + causal unscaled curriculum feature "
            "values"),
    }
