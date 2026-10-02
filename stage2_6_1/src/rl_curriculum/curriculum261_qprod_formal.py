"""QProd 正式启动准备层(RouteC_FormalLaunch_Preparation_v1)。

本模块是**尚未激活**的正式启动适配:提供正式上下文组装、正式批准
原件校验、正式许可校验、Level B 正式研究计划构建与只读预检。
真实正式运行(Level A/B)保持 NOT_RUN,直至:

1. 受信任部署配置 ``<deploy_root>/qprod_deploy_config.json`` 以
   mode=formal_ready 写入(由用户批准后操作员执行,本模块不写);
2. 用户批准原件(create-only 记录进正式 authority 目录);
3. 正式许可由 formal authority 依批准原件签发(签发能力只在
   runner ``qprod_formal_authority.py``,不在被验 src);
4. 本模块的 launch 入口在第一项受控副作用之前完成全部校验,
   无批准/错绑定即拒绝(零写入、零业务叶调用)。

明确边界:本模块不注册正式运行实例、不消耗正式 exposure、不生成
研究数据、不 fit 新 bundle、不更新/加载模型;Level B 正式
namespace 以休眠定义加入(curriculum261_api),仅使 seed 派生
可达,实际生成仍被许可/坐标锁/一次性消费链拦截。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import (
    QProdContext, QProdContextError, QPROD_DEPLOY_CONFIG_FORMAT,
    QPROD_DEPLOY_CONFIG_NAME, QPROD_DEPLOY_MODES, QPROD_ROOT_ENV_VARS,
    _canonical_json, _is_within, harden_root, load_deploy_config,
)
from rl_curriculum.curriculum261_qprod_permit import (
    QPROD_PERMIT_DIGEST_PREFIX, permit_digest, validate_permit,
)
from rl_curriculum.curriculum261_qprod_plan import (
    QPROD_RESEARCH_PLAN_FORMAT, research_plan_digest,
    research_plan_structure_problems,
)
from rl_curriculum.curriculum261_qprod_coordinate import (
    FORMAL_BLOCKS_PER_CORPUS, FORMAL_MC_EVENTS, QPROD_MAX_ATTEMPTS,
)

#: 正式迭代身份(与全部工程迭代 qprod_{a,b}_eng_v1、历史 R17/R18/R19
#: 尝试互不重叠;A/B 之间也不可混用)。
QPROD_FORMAL_LEVEL_A_ITERATION_ID = "qprod_a_formal_v1"
QPROD_FORMAL_LEVEL_B_ITERATION_ID = "qprod_b_formal_v1"

#: 固定共同锚 P0(R25 dev_plan 历史开发参照,条件口径:不是本轮估计,
#: 不声称真实总体锚已知;正式采纳属用户待批决定)。
QPROD_FORMAL_P0_REFERENCE = 0.950431552876822
QPROD_FORMAL_P0_SOURCE_LABEL = (
    "R25 dev_plan.json study.p0_fixed_reference(历史开发研究参照;"
    "固定共同锚的条件口径,非本轮新估计;正式采纳待用户批准)")

#: 拟议停止模式(collect_all_k:保留来源有效的统计负结果;技术无效/
#: 中断不补抽、不换 seed;DECISIONS_FOR_PREPARATION 拟议默认,待批)。
QPROD_FORMAL_STOP_MODE = "collect_all_k"

#: 每坐标正式审计常量(与坐标锁/审计核心冻结常量一致;执行侧仍由
#: lock_coordinate_audit_plan 三方对账强制,此处仅用于计划构建与
#: 预检对拍)。
QPROD_FORMAL_EPISODES_PER_BLOCK = 8          # 4 rung x A/B(内核冻结)
QPROD_FORMAL_PLANNED_K = 11

#: 正式 Level B 坐标清单(事前冻结;namespace 为休眠正式名单成员,
#: 与工程坐标/开发研究坐标互不相交)。
QPROD_FORMAL_COORDINATE_IDS = tuple(
    f"c{idx:02d}" for idx in range(1, QPROD_FORMAL_PLANNED_K + 1))


def formal_coordinate_manifest() -> list[dict[str, Any]]:
    """正式 Level B 的 11 坐标清单(c01..c11;零生成构建)。"""
    return [
        {
            "coordinate_id": cid,
            "model_namespace": f"cue_qprod_formal_v1_{cid}_model",
            "validation_namespace": f"cue_qprod_formal_v1_{cid}_validation",
            "blocks_per_corpus": FORMAL_BLOCKS_PER_CORPUS,
            "mc_events": FORMAL_MC_EVENTS,
            "max_attempts": QPROD_MAX_ATTEMPTS,
            "artifact_subdir": f"coord_{cid}",
        }
        for cid in QPROD_FORMAL_COORDINATE_IDS
    ]


def formal_level_b_quota() -> dict[str, int]:
    """正式 Level B 许可配额(逐项可复算推导;不拍脑袋)。

    - max_leaf_calls_per_coordinate:单坐标 episode 叶动作最坏上界
      = model once 500x8 + validation attempts 最坏 500x5x8 +
      完整性 bitwise 重放上界 500x8 = 28000(账本以 8 episode/动作
      计,attempts 按 attempts_made 精确回填;额度不足在动作前拒绝);
    - max_successful_episodes_total:11 坐标 x 500 blocks x 8 x 双
      语料 = 88000;
    - mc_events_per_coordinate:1e6(与核心冻结常量一致);
    - max_native_executions:11(每坐标一次原生执行)。
    """
    blocks = FORMAL_BLOCKS_PER_CORPUS
    per_block = QPROD_FORMAL_EPISODES_PER_BLOCK
    return {
        "max_leaf_calls_per_coordinate": blocks * per_block * (
            1 + QPROD_MAX_ATTEMPTS + 1),
        "max_successful_episodes_total": (
            QPROD_FORMAL_PLANNED_K * blocks * per_block * 2),
        "mc_events_per_coordinate": FORMAL_MC_EVENTS,
        "max_native_executions": QPROD_FORMAL_PLANNED_K,
    }


# ------------------------------------------------ 计划构建 ----------
#: Level A 预算表(逐步骤真实消耗;来源行号见
#: artifacts/repair17/development/formal_launch_prep_v1 技术附录;
#: 不确定项如实标注,不虚构精度)。仅用于计划/预检/批准摘要;
#: 执行侧预算由链自身冻结常量与许可配额强制。
QPROD_FORMAL_LEVEL_A_BUDGET = {
    "episodes_upper_bound": 16000,
    "episodes_note": (
        "determinism ~300 + audit 48 + cue-audit 8000(+重放<=400) + "
        "preplan 24 + design >=2560(候选级不确定) + calibrate ~4400 + "
        "qualify ~2300 + smoke 146;上界按各步冻结常量推导"),
    "v2_preprocessor_fits": 5,
    "v2_fits_note": (
        "determinism 1 + calibrate main/holdout 2 + qualify 1 + "
        "smoke 1(audit 不做 V2 fit)"),
    "supervised_mlp_fits_upper": 84,
    "supervised_note": (
        "calibrate ~54 + qualify ~27 + determinism 工程 3;控制组"
        "计法存在不确定,按上界记账"),
    "mc_events_total": 1_000_000,
    "bootstrap_resamples_upper": 1_160_000,
    "optimizer_updates": 1,
    "optimizer_note": (
        "仅第 14 步 smoke:model.learn(total_timesteps=256) 恰 256 "
        "环境交互步、1 次 optimizer 更新;资格 PASS 后才执行"
        "(postcondition final_verdict_pass)"),
    "subprocesses_upper": 35,
}


def build_formal_level_b_plan(
        *, code_freeze_sha: str,
        code_identity: dict[str, Any]) -> dict[str, Any]:
    """正式 Level B 研究计划载荷(数据前;冻结前可算 digest)。

    结构必须通过 research_plan_structure_problems(profile=formal
    分支:blocks 500/MC 1e6/episodes 8)。
    """
    payload = {
        "format": QPROD_RESEARCH_PLAN_FORMAT,
        "level": "level_b",
        "iteration_id": QPROD_FORMAL_LEVEL_B_ITERATION_ID,
        "profile": "formal",
        "code_freeze_sha": code_freeze_sha,
        "coordinate_manifest": formal_coordinate_manifest(),
        "rules": {
            "p0_fixed_reference": QPROD_FORMAL_P0_REFERENCE,
            "p0_source_label": QPROD_FORMAL_P0_SOURCE_LABEL,
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003,
            "alpha": 0.05,
            "r_analysis": 1.5,
            "planned_k": QPROD_FORMAL_PLANNED_K,
            "audit_budgets": {
                "blocks_per_corpus": FORMAL_BLOCKS_PER_CORPUS,
                "mc_events": FORMAL_MC_EVENTS,
                "episodes_per_block": QPROD_FORMAL_EPISODES_PER_BLOCK,
            },
            "anchor_policy": (
                "固定共同 P0(外部计划显式给定);局部 p_contract 照"
                "真实算法计算,不因数值不等删坐标;固定参照的条件推断"
                "不改说成随机重估锚的无条件证明"),
            "stop_policy": (
                "collect_all_k:统计负结果保留并收齐 K;技术无效/中断"
                "停止不安全后续,不补抽、不换 seed"),
        },
        "quota": formal_level_b_quota(),
        "code_identity": dict(code_identity),
        "stop_mode": QPROD_FORMAL_STOP_MODE,
        "engineering_only": False,
    }
    problems = research_plan_structure_problems(payload)
    if problems:
        raise QProdContextError(
            f"正式 Level B 计划载荷结构问题(不应发生): {problems}")
    return payload


# ------------------------------------------------ 批准原件 ----------
QPROD_FORMAL_APPROVAL_FORMAT = "cur261-qprod-formal-approval-v1"
QPROD_FORMAL_APPROVAL_PREFIX = "qfap-"
QPROD_FORMAL_AUTHORITY_KIND = "formal_admission_authority"

QPROD_FORMAL_APPROVAL_REQUIRED_KEYS = (
    "format", "approval_id", "task_level", "iteration_id",
    "approved", "approval_source", "approval_digest",
)
QPROD_FORMAL_APPROVAL_APPROVED_KEYS = (
    "research_plan_digest", "code_freeze_sha", "artifact_root",
    "state_root", "authority_dir", "namespaces", "coordinate_ids",
    "quota", "authorized_stop_after", "model_update_authorized",
)


def formal_approval_name(level: str, iteration_id: str) -> str:
    return f"qprod_formal_approval_{level}_{iteration_id}.json"


def formal_approval_digest(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items()
            if k != "approval_digest"}
    return QPROD_FORMAL_APPROVAL_PREFIX + hashlib.sha256(
        _canonical_json(body).encode("utf-8")).hexdigest()


def load_formal_approval(authority_dir: Path | str, *, level: str,
                         iteration_id: str) -> dict[str, Any]:
    path = Path(authority_dir) / formal_approval_name(
        level, iteration_id)
    if not path.is_file():
        raise QProdContextError(
            f"正式批准原件缺失: {path}(没有用户批准,不签发、不启动;"
            f"预检不把缺失批准当阻塞,launch 在受控副作用前拒绝)")
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QProdContextError(f"正式批准原件不可解析: {exc}") from exc
    if not isinstance(approval, dict):
        raise QProdContextError("正式批准原件必须是 JSON 对象")
    return approval


def validate_formal_approval(
        approval: dict[str, Any], *, level: str, iteration_id: str,
        artifact_root: Path, state_root: Path, authority_dir: Path,
        code_freeze_sha: str, research_plan_digest: str,
        namespaces: list[str] | tuple[str, ...],
        coordinate_ids: list[str] | tuple[str, ...],
        quota: dict[str, int],
        authorized_stop_after: str | None = None,
        model_update_authorized: bool = False) -> dict[str, Any]:
    """批准原件逐项绑定校验(fail closed;任何错绑定即拒)。

    批准必须绑定:层/迭代、候选(code_freeze_sha=Commit A)、计划
    digest、canonical 根、authority、输入范围、配额、停止边界与
    是否授权链内模型更新。普通执行包自写 PASS、复制工程许可或
    重算摘要都过不了这里——批准身份是 authority 目录内的
    create-only 原件,不是可重算字段。
    """
    missing = [k for k in QPROD_FORMAL_APPROVAL_REQUIRED_KEYS
               if k not in approval]
    if missing:
        raise QProdContextError(f"批准原件缺字段: {missing}")
    if approval["format"] != QPROD_FORMAL_APPROVAL_FORMAT:
        raise QProdContextError(
            f"批准 format {approval['format']!r} 不识别")
    if approval["approval_digest"] != formal_approval_digest(approval):
        raise QProdContextError(
            "批准 digest 失配(原件被改或伪造;重算不构成批准)")
    if approval["task_level"] != level:
        raise QProdContextError(
            f"批准层 {approval['task_level']!r} != 请求 {level!r}"
            f"(A/B 批准不可互用)")
    if approval["iteration_id"] != iteration_id:
        raise QProdContextError(
            f"批准迭代 {approval['iteration_id']!r} != 请求 "
            f"{iteration_id!r}")
    approved = approval["approved"]
    if not isinstance(approved, dict):
        raise QProdContextError("approved 必须是对象")
    missing_a = [k for k in QPROD_FORMAL_APPROVAL_APPROVED_KEYS
                 if k not in approved]
    if missing_a:
        raise QProdContextError(f"approved 缺字段: {missing_a}")
    if approved["research_plan_digest"] != research_plan_digest:
        raise QProdContextError(
            f"批准绑定计划 {approved['research_plan_digest']!r} != "
            f"当前计划 {research_plan_digest!r}(错计划拒绝;批准不"
            f"自动延及另一份计划)")
    if approved["code_freeze_sha"] != code_freeze_sha:
        raise QProdContextError(
            f"批准候选 {approved['code_freeze_sha']!r} != 请求 "
            f"{code_freeze_sha!r}(错候选拒绝)")
    for key, want in (("artifact_root", artifact_root),
                      ("state_root", state_root),
                      ("authority_dir", authority_dir)):
        if Path(str(approved[key])).resolve() != Path(want).resolve():
            raise QProdContextError(
                f"批准绑定 {key} {approved[key]!r} != 当前 "
                f"{str(want)!r}(错根拒绝;批准不可换根使用)")
    if sorted(approved["namespaces"] or []) != sorted(namespaces):
        approved_ns = sorted(approved["namespaces"] or [])
        raise QProdContextError(
            f"批准输入范围 namespaces {approved_ns} != 请求 "
            f"{sorted(namespaces)}(错范围拒绝)")
    if sorted(approved["coordinate_ids"] or []) != sorted(coordinate_ids):
        raise QProdContextError(
            f"批准坐标范围 {sorted(approved['coordinate_ids'] or [])} "
            f"!= 请求 {sorted(coordinate_ids)}(错范围拒绝)")
    if approved["quota"] != dict(quota):
        raise QProdContextError(
            f"批准配额 {approved['quota']!r} != 请求 {dict(quota)!r}"
            f"(额度以批准为准,不可放大)")
    if approved["authorized_stop_after"] != authorized_stop_after:
        raise QProdContextError(
            f"批准停止边界 {approved['authorized_stop_after']!r} != "
            f"请求 {authorized_stop_after!r}")
    if bool(approved["model_update_authorized"]) is not bool(
            model_update_authorized):
        raise QProdContextError(
            f"批准 model_update_authorized="
            f"{approved['model_update_authorized']!r} != 请求 "
            f"{model_update_authorized!r}(链内 smoke/模型更新授权"
            f"不含糊)")
    src = approval["approval_source"]
    if not isinstance(src, dict) or src.get(
            "kind") != "user_direct_approval" or not src.get(
                "statement_digest"):
        raise QProdContextError(
            f"批准来源非法: {src!r}(须绑定用户批准原文 digest)")
    return approval


# ------------------------------------------------ 正式上下文 --------
def _read_formal_roots(deploy_root: Path | str, *, level: str,
                       iteration_id: str,
                       ) -> tuple[Path, Path, Path]:
    """读正式根/authority(零 mkdir;launch 在门禁后另行创建)。

    与 resolve_formal_roots 相同的拒绝语义(环境重定向即拒、
    formal_ready 必需、根齐备),但不产生任何目录副作用——预检与
    launch 门禁阶段都用本函数,目录创建只发生在受控写阶段。
    """
    deploy_root = Path(deploy_root).resolve()
    for var in QPROD_ROOT_ENV_VARS:
        if os.environ.get(var):
            raise QProdContextError(
                f"正式入口拒绝环境重定向 {var}(受信任部署配置是唯一"
                f"根来源)")
    if level not in ("level_a", "level_b"):
        raise QProdContextError(f"未知层 {level!r}")
    cfg = load_deploy_config(deploy_root)
    if cfg.get("mode") != "formal_ready":
        raise QProdContextError(
            f"部署配置 mode={cfg.get('mode')!r} 非 formal_ready"
            f"(正式 Level A/B 保持 NOT_RUN;不支持改目录或换参数冒充"
            f"正式部署;合法 mode: {QPROD_DEPLOY_MODES})")
    entries = cfg.get("formal_roots") or {}
    entry = entries.get(iteration_id)
    if not isinstance(entry, dict):
        raise QProdContextError(
            f"部署配置 formal_roots 缺迭代 {iteration_id!r}(受信任"
            f"配置未登记该正式迭代)")
    roots = []
    for key in ("artifact_root", "state_root"):
        raw = entry.get(key)
        if not raw:
            raise QProdContextError(
                f"formal_roots[{iteration_id!r}] 缺 {key}")
        roots.append(harden_root(raw, label=key, create=False))
    art, state = roots
    authority = harden_root(entry.get("authority_dir", ""),
                            label="authority_dir", create=False)
    if authority == art or authority == state:
        raise QProdContextError(
            "authority 目录不得与正式根相同(自授权拒绝)")
    if _is_within(authority, art) or _is_within(authority, state):
        raise QProdContextError(
            "authority 目录不得位于正式根内(签发必须在被验包写"
            "边界之外;自授权拒绝)")
    return art, state, authority


def build_formal_context(
        deploy_root: Path | str, *, level: str, iteration_id: str,
        code_freeze_sha: str, research_plan_digest: str,
        approval_digest: str) -> QProdContext:
    """组装正式上下文(纯数据组装;不创建目录、不写状态)。"""
    art, state, authority = _read_formal_roots(
        deploy_root, level=level, iteration_id=iteration_id)
    return QProdContext(
        level=level,
        iteration_id=iteration_id,
        profile="formal",
        artifact_root=art,
        state_root=state,
        code_freeze_sha=code_freeze_sha,
        plan_identity={
            "research_plan_digest": research_plan_digest,
            "approval_digest": approval_digest,
        },
        permit_path=authority / (
            f"qprod_permit_{level}_{iteration_id}.json"),
        authority_dir=authority,
    )


#: 正式许可附加字段(在通用 11 键之上;缺失即拒)。
QPROD_FORMAL_PERMIT_EXTRA_KEYS = (
    "research_plan_digest", "approval_digest",
)


def validate_formal_permit(permit_path: Path | str, *,
                           context: QProdContext) -> dict[str, Any]:
    """正式许可校验 = 通用校验 + 正式绑定(只读,不消费)。

    通用 validate_permit 已覆盖:authority 目录内、结构/digest、
    层/迭代/冻结 SHA/两根、issuer 种类= formal_admission_authority
    (profile 绑定)、scope/配额结构。本函数追加:
    - 许可必须绑定与上下文一致的 research_plan_digest;
    - 许可必须绑定 approval_digest,且 authority 目录内存在同
      digest 的批准原件,其绑定与许可逐项一致。
    """
    permit = validate_permit(permit_path, context=context)
    missing = [k for k in QPROD_FORMAL_PERMIT_EXTRA_KEYS
               if k not in permit]
    if missing:
        raise QProdContextError(
            f"正式许可缺绑定字段: {missing}(计划/批准绑定必须随许可"
            f"签发,不可事后补)")
    plan_digest = context.plan_identity.get("research_plan_digest")
    if permit["research_plan_digest"] != plan_digest:
        raise QProdContextError(
            f"许可绑定计划 {permit['research_plan_digest']!r} != 上下"
            f"文 {plan_digest!r}(错计划拒绝;证据提交不能冒充另一份"
            f"被批计划)")
    approval = load_formal_approval(
        context.authority_dir, level=context.level,
        iteration_id=context.iteration_id)
    if approval.get("approval_digest") != permit["approval_digest"]:
        raise QProdContextError(
            "许可绑定批准 digest 与 authority 内批准原件不一致"
            "(错批准拒绝)")
    if approval.get("approval_digest") != formal_approval_digest(
            approval):
        raise QProdContextError("批准原件 digest 失配(被改或伪造)")
    approved = approval.get("approved") or {}
    for key, want in (
            ("code_freeze_sha", permit["code_freeze_sha"]),
            ("research_plan_digest", permit["research_plan_digest"]),
    ):
        if approved.get(key) != want:
            raise QProdContextError(
                f"批准绑定 {key}={approved.get(key)!r} != 许可 "
                f"{want!r}(批准与许可不一致;不可各取一半)")
    for key in ("task_level", "iteration_id"):
        if approval.get(key) != permit[key]:
            raise QProdContextError(
                f"批准绑定 {key}={approval.get(key)!r} != 许可 "
                f"{permit[key]!r}(批准与许可不一致;不可各取一半)")
    return permit


# ------------------------------------------------ 预检(只读) -------
def _preflight_snapshot(root: Path) -> list[str]:
    """受保护根的只读快照(前后对照用;不存在即空)。"""
    if not root.exists():
        return []
    return sorted(
        str(p.relative_to(root)) for p in root.rglob("*")
        if p.is_file())[:4000]


def preflight_content_identity(report: dict[str, Any]) -> str:
    """预检内容身份(排除时间戳;重复预检身份不变)。"""
    body = {k: v for k, v in report.items()
            if k not in ("generated_utc", "content_identity")}
    return "qfpf-" + hashlib.sha256(
        _canonical_json(body).encode("utf-8")).hexdigest()


def preflight_formal_level_b(
        deploy_root: Path | str, *, code_freeze_sha: str,
        code_identity: dict[str, Any]) -> dict[str, Any]:
    """Level B 正式预检(零生成、零写入;可重复,身份稳定)。

    逐项检查:部署配置/根、计划 digest 身份与结构、11 坐标的
    namespace/预算/子目录/seed 派生与跨坐标不碰撞、配额覆盖。
    """
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_QPROD_FORMAL_NAMESPACES,
    )
    from rl_curriculum.curriculum261_r6_tape import derive261_block_seed

    findings: list[str] = []
    deployment_ok = True
    try:
        art, state, authority = _read_formal_roots(
            deploy_root, level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID)
    except QProdContextError as exc:
        deployment_ok = False
        findings.append(f"deployment: {exc}")
        art = state = authority = None  # type: ignore[assignment]

    payload = build_formal_level_b_plan(
        code_freeze_sha=code_freeze_sha, code_identity=code_identity)
    digest = research_plan_digest(payload)
    problems = research_plan_structure_problems(payload)
    if problems:
        findings.append(f"plan_structure: {problems}")
    coordinates = []
    seed_uniqueness: dict[int, list[str]] = {}
    for coord in payload["coordinate_manifest"]:
        entry: dict[str, Any] = {
            "coordinate_id": coord["coordinate_id"], "checks": [],
        }
        ok = True
        for key in ("model_namespace", "validation_namespace"):
            ns = coord[key]
            if ns not in CURRICULUM261_QPROD_FORMAL_NAMESPACES:
                entry["checks"].append(
                    f"{key}={ns!r} 不在正式休眠名单")
                ok = False
        if coord["blocks_per_corpus"] != FORMAL_BLOCKS_PER_CORPUS \
                or coord["mc_events"] != FORMAL_MC_EVENTS \
                or coord["max_attempts"] != QPROD_MAX_ATTEMPTS:
            entry["checks"].append("预算与正式常量不一致")
            ok = False
        # seed 派生(纯推导,零生成):block 0 的 model once + validation
        # attempts 0..4,并记录跨坐标唯一性。
        for ns in (coord["model_namespace"],
                   coord["validation_namespace"]):
            for attempt in range(QPROD_MAX_ATTEMPTS):
                seed = derive261_block_seed(ns, 0, attempt)
                seed_uniqueness.setdefault(seed, []).append(
                    f"{coord['coordinate_id']}:{ns}:a{attempt}")
        entry["namespace_ok"] = ok
        coordinates.append(entry)
    collisions = {seed: refs for seed, refs in seed_uniqueness.items()
                  if len(refs) > 1}
    if collisions:
        findings.append(
            f"seed 跨坐标碰撞(不应发生): "
            f"{ {str(s): r for s, r in list(collisions.items())[:3]} }")
    quota_ok = True
    need_eps_per_coord = FORMAL_BLOCKS_PER_CORPUS * \
        QPROD_FORMAL_EPISODES_PER_BLOCK * 2
    q = payload["quota"]
    if q["mc_events_per_coordinate"] < FORMAL_MC_EVENTS:
        findings.append("配额 mc_events_per_coordinate < 正式常量")
        quota_ok = False
    if q["max_successful_episodes_total"] < need_eps_per_coord:
        findings.append("配额总额度不足以覆盖单坐标成功正文需求")
        quota_ok = False
    if q["max_native_executions"] < QPROD_FORMAL_PLANNED_K:
        findings.append("配额 max_native_executions < 11 坐标需求")
        quota_ok = False
    report = {
        "format": "cur261-qprod-formal-preflight-v1",
        "level": "level_b",
        "iteration_id": QPROD_FORMAL_LEVEL_B_ITERATION_ID,
        "deployment_ok": deployment_ok,
        "deployment_note": (
            "正式执行未授权是预期状态:生产部署配置不存在/非 "
            "formal_ready 时 deployment_ok=false,预检如实记录,不"
            "视为工程失败;launch 恒拒" if not deployment_ok else
            "受信任部署配置 formal_ready(测试域沙盒)"),
        "plan_digest": digest,
        "plan_structure_problems": problems,
        "coordinates": coordinates,
        "quota": q,
        "quota_covers_needs": quota_ok,
        "findings": findings,
        "business_leaf_calls": 0,
        "status": "PREPARED_PENDING_USER_APPROVAL" if (
            deployment_ok and not findings) else "FINDINGS_PRESENT",
        "generated_utc": _utc_now(),
    }
    report["content_identity"] = preflight_content_identity(report)
    return report


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "QPROD_FORMAL_LEVEL_A_ITERATION_ID",
    "QPROD_FORMAL_LEVEL_B_ITERATION_ID",
    "QPROD_FORMAL_P0_REFERENCE", "QPROD_FORMAL_P0_SOURCE_LABEL",
    "QPROD_FORMAL_STOP_MODE", "QPROD_FORMAL_PLANNED_K",
    "QPROD_FORMAL_COORDINATE_IDS", "formal_coordinate_manifest",
    "formal_level_b_quota", "QPROD_FORMAL_LEVEL_A_BUDGET",
    "build_formal_level_b_plan", "QPROD_FORMAL_APPROVAL_FORMAT",
    "QPROD_FORMAL_APPROVAL_PREFIX", "QPROD_FORMAL_AUTHORITY_KIND",
    "QPROD_FORMAL_APPROVAL_REQUIRED_KEYS",
    "QPROD_FORMAL_APPROVAL_APPROVED_KEYS",
    "formal_approval_name", "formal_approval_digest",
    "load_formal_approval", "validate_formal_approval",
    "_read_formal_roots", "build_formal_context",
    "QPROD_FORMAL_PERMIT_EXTRA_KEYS", "validate_formal_permit",
    "preflight_content_identity", "preflight_formal_level_b",
    "QPROD_DEPLOY_CONFIG_NAME", "QPROD_DEPLOY_CONFIG_FORMAT",
    "permit_digest", "QPROD_PERMIT_DIGEST_PREFIX",
]
