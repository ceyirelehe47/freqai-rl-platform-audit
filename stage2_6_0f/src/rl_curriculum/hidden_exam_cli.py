"""阶段 2.6.0a 工作包 E/F/G/H + 2.6.0b 工作包 C + 2.6.0c 工作包 A
+ 2.6.0f 工作包 A:密封隐藏考试 CLI(v7)。

正式(密封)模式:
    python -m rl_curriculum.hidden_exam_cli \
        --sealed-manifest commitment.json --pack pack.json \
        --checkpoint model.zip --context ctx.json --out result.json \
        --retire-registry retired.json --attempt-registry attempts.json \
        --builder-provider mock [--detailed detailed.json]

阶段 2.6.0f 工作包 A:
- --builder-provider 必填(mock | private):评估方宿主从评估方只读
  配置选择 Builder Identity Provider;private 需同时提供
  --builder-provider-root(私有 builder package 目录)。Provider 不
  来自 context、pack、checkpoint 或候选任何一方;正式调用缺
  Provider -> EXAM_INVALID(执行器 fail closed,无 mock fallback)。
  sealed-exam-context-v3 不新增任何 builder provider 信任根字段。

阶段 2.6.0c 工作包 A:
- issuer 信任根收归 sealed commitment:CLI 不再从 context 读取并传入
  issuer(旧通道允许"保留承诺、替换 context issuer、自签 checkpoint"
  的覆盖攻击);context 的 trusted_issuer 只是展示副本,执行器将其
  与承诺做逐字段 canonical equality,不一致 -> EXAM_INVALID。

阶段 2.6.0b(C1):
- --no-subprocess 已删除:正式候选永远在系统级沙箱内执行(unshare
  namespaces + Landlock + rlimits);任何请求正式考试但未启用沙箱的
  行为直接 EXAM_INVALID。进程内执行只允许 --dev(public pack,输出
  formal_conclusion=false)或单元测试专用入口。
- checkpoint 必须持有受信 training attestation(sidecar 自声明无效);
- 密封承诺 v3 逐项验证(含沙箱 profile/候选运行时 manifest/严格
  Null 真实报告/受信 issuer 自洽/逐族生成器实现指纹/nuisance 等价
  区间/复制门槛与 seed 聚合规则)。

- --sealed-manifest 必填;--fee/--slippage/--window-size/--initial-cash
  在正式模式提供即拒绝(考试条件由 sealed manifest 与考试上下文冻结);
- PASS/FAIL/SUSPECTED_CHEATING/EXAM_INVALID 由冻结判定器产生;
- 默认输出最小化;--detailed 写出详细结果的同时退休该考试包;
- attempt registry 幂等:同 (checkpoint, pack) 重跑返回同一结果。

开发模式(--dev):仅允许 visibility=public 的公开开发考试;允许参数
覆盖;输出明确标记 formal_conclusion=false(不产生正式毕业结论)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rl_platform.fingerprint import dependency_versions
from rl_platform.versions import spec_versions
from rl_curriculum.evaluator import (
    EvalConfig,
    evaluator_code_hash,
    evaluate_policy,
)
from rl_curriculum.exam_pack import (
    ExamPack,
    RetirementRegistry,
    materialize_pack,
    redact_report,
)
from rl_curriculum.formal_exam import (
    EXAM_CLI_VERSION,
    EXAM_INVALID_EXIT_CODE,
    run_sealed_exam,
)
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.policies import (
    AlwaysFlatPolicy,
    AlwaysLongPolicy,
    HighTurnoverPolicy,
    OneStepGreedyPolicy,
    OracleSegmentedDriftPolicy,
    OracleSmoothLatentDriftPolicy,
    PeriodicTogglePolicy,
    RandomPolicy,
    RuleTrendPolicy,
)

#: CLI 版本常量统一由 formal_exam 定义(旧版本在两文件重复定义)
CLI_VERSION = EXAM_CLI_VERSION

POLICY_ALIASES = {
    "always_flat": AlwaysFlatPolicy,
    "always_long": AlwaysLongPolicy,
    "random": RandomPolicy,
    "periodic_toggle": PeriodicTogglePolicy,
    "one_step_greedy": OneStepGreedyPolicy,
    "high_turnover": HighTurnoverPolicy,
    "rule_trend": RuleTrendPolicy,
    "oracle_segmented_drift": OracleSegmentedDriftPolicy,
    "oracle_smooth_latent_drift": OracleSmoothLatentDriftPolicy,
}

# 正式模式禁止的考试条件覆盖参数(密封条件不可命令行改写)
SEALED_FORBIDDEN_OVERRIDES = ("fee", "slippage_bps", "window_size",
                              "initial_cash")


def _build_dev_policy(spec: str):
    if spec.startswith("sb3:"):
        raise SystemExit(
            "开发模式不加载 checkpoint(正式 checkpoint 只经密封模式评估;"
            "请使用 --sealed-manifest)"
        )
    if spec not in POLICY_ALIASES:
        raise SystemExit(
            f"未知策略 {spec!r}:可选 {sorted(POLICY_ALIASES)}"
        )
    return POLICY_ALIASES[spec]()


def _run_dev_mode(args, started) -> int:
    """公开开发考试:参数可覆盖,但 formal_conclusion 恒为 false。"""
    import pandas as pd

    pack = ExamPack.load(args.pack)
    if pack.visibility != "public":
        raise SystemExit(
            f"--dev 只允许 visibility=public 的公开开发考试,"
            f"收到 {pack.visibility!r}(mock_hidden/隐藏考试必须走密封模式)"
        )
    from rl_curriculum.probe_charter import probe_observation_schema

    schema = probe_observation_schema()
    cfg = EvalConfig(
        fee=args.fee if args.fee is not None else 0.001,
        slippage_bps=args.slippage_bps if args.slippage_bps is not None else 0.0,
        initial_cash=args.initial_cash if args.initial_cash is not None else 100.0,
        window_size=args.window_size if args.window_size is not None else 1,
    )
    policy = _build_dev_policy(args.policy)
    episodes = materialize_pack(
        pack, DEFAULT_GENERATOR_REGISTRY,
        retire_registry=RetirementRegistry(args.retire_registry)
        if args.retire_registry else None,
    )
    report = evaluate_policy(
        policy, episodes, cfg, schema,
        baseline_policies={
            "always_flat": AlwaysFlatPolicy(),
            "rule_trend": RuleTrendPolicy(),
        },
    )
    out = {
        "exam_cli_version": CLI_VERSION,
        "mode": "dev",
        "formal_conclusion": False,
        "pack_name": pack.name,
        "pack_hash": pack.pack_hash(),
        "policy": args.policy,
        "status": "DEV_ONLY",
        "note": "公开开发考试:不产生正式毕业结论;"
                "进程内执行仅允许此模式与单元测试入口(沙箱外)",
        "spec_versions": spec_versions(),
        "evaluator_code_hash": evaluator_code_hash(),
        "dependencies": dependency_versions(),
        "started_utc": started,
        "finished_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "exit_code": 0,
        "aggregate": redact_report(report, pack.visibility),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[hidden_exam_cli:dev] DEV_ONLY -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    ap = argparse.ArgumentParser(description="密封隐藏考试 CLI(v4)")
    ap.add_argument("--sealed-manifest", default=None,
                    help="密封承诺 v3(正式模式必填)")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--checkpoint", default=None,
                    help="SB3 checkpoint(密封模式必填)")
    ap.add_argument("--context", default=None,
                    help="考试上下文(charter/schema/verdict/EvalConfig/"
                         "sandbox profile;issuer 仅为展示副本,信任根"
                         "唯一来自 sealed manifest)")
    ap.add_argument("--policy", default=None,
                    help="开发模式策略别名")
    ap.add_argument("--out", required=True)
    ap.add_argument("--retire-registry", default=None)
    ap.add_argument("--attempt-registry", default=None)
    ap.add_argument("--detailed", default=None,
                    help="写出详细结果(将立即退休该考试包)")
    ap.add_argument("--dev", action="store_true",
                    help="公开开发考试(public pack;formal_conclusion=false)")
    # 阶段 2.6.0f 工作包 A:评估方宿主从只读配置选择 Builder
    # Identity Provider(候选/context/pack/checkpoint 均不可选择)
    ap.add_argument("--builder-provider", default=None,
                    choices=("mock", "private"),
                    help="评估方 Builder Identity Provider 类型(mock=公开"
                         "mock builder;private=评估方私有 builder package)"
                    )
    ap.add_argument("--builder-provider-root", default=None,
                    help="private Provider 的私有 builder package 根目录"
                         "(--builder-provider private 时必填;不得位于"
                         "候选可写目录)")
    # 考试条件覆盖参数:正式模式提供即拒绝(密封条件不可改写)
    ap.add_argument("--fee", type=float, default=None)
    ap.add_argument("--slippage", dest="slippage_bps", type=float, default=None)
    ap.add_argument("--window-size", dest="window_size", type=int, default=None)
    ap.add_argument("--initial-cash", dest="initial_cash", type=float,
                    default=None)
    args = ap.parse_args(argv)
    # 工作包 C1:--no-subprocess 已删除(源码级断言其不存在)
    assert not hasattr(args, "no_subprocess"), \
        "--no-subprocess 必须不存在(正式沙箱不可绕过)"

    started = pd.Timestamp.now(tz="UTC").isoformat()

    if args.dev:
        return _run_dev_mode(args, started)

    # ---- 正式(密封)模式 ------------------------------------------------
    if not args.sealed_manifest:
        print(
            "[hidden_exam_cli] 正式模式必须提供 --sealed-manifest:"
            "隐藏考试必须由独立评估方预先承诺,不存在无承诺通道",
            file=sys.stderr,
        )
        return 2
    provided_overrides = [
        f"--{f.replace('_', '-')}" for f in SEALED_FORBIDDEN_OVERRIDES
        if getattr(args, f) is not None
    ]
    if provided_overrides:
        print(
            f"[hidden_exam_cli] 正式模式拒绝考试条件覆盖参数 "
            f"{provided_overrides}:fee/滑点/初始资金/窗口由 sealed "
            f"manifest 与考试上下文冻结,不得命令行改写"
            f"(无'忽略哈希/强制继续'参数;开发调参请用 --dev)",
            file=sys.stderr,
        )
        return 2
    if not args.checkpoint:
        print("[hidden_exam_cli] 正式模式必须提供 --checkpoint", file=sys.stderr)
        return 2
    if not args.context:
        print("[hidden_exam_cli] 正式模式必须提供 --context", file=sys.stderr)
        return 2

    from rl_curriculum.mock_sealed_exam import load_exam_context

    # ---- 工作包 A:Provider 只由评估方宿主 CLI 配置选择(context /
    #      pack / checkpoint / 候选命令行参数都不能选择 Provider)
    builder_provider = None
    if args.builder_provider == "mock":
        from rl_curriculum.builder_identity import (
            MockBuilderIdentityProvider,
        )

        builder_provider = MockBuilderIdentityProvider()
    elif args.builder_provider == "private":
        if not args.builder_provider_root:
            print(
                "[hidden_exam_cli] --builder-provider private 必须提供 "
                "--builder-provider-root(评估方私有 builder package 目录)",
                file=sys.stderr,
            )
            return 2
        from rl_curriculum.builder_identity import (
            PrivateBuilderIdentityProvider,
        )

        # entrypoint 声明来自评估方只读配置文件(provider_config.json)
        import json as _json

        cfg_path = Path(args.builder_provider_root) / "provider_config.json"
        if not cfg_path.is_file():
            print(
                f"[hidden_exam_cli] 私有 Provider 配置缺失: {cfg_path}",
                file=sys.stderr,
            )
            return 2
        pcfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
        builder_provider = PrivateBuilderIdentityProvider(
            args.builder_provider_root,
            entrypoint_module=pcfg["entrypoint_module"],
            entrypoint_qualname=pcfg["entrypoint_qualname"],
            attempt_loop_module=pcfg.get("attempt_loop_module", ""),
            attempt_loop_qualname=pcfg.get("attempt_loop_qualname", ""),
            params_spec=pcfg.get("params_spec"),
            families=pcfg.get("families"),
            root_label=pcfg.get("root_label", "private-builder"),
        )
    else:
        print(
            "[hidden_exam_cli] 正式模式必须提供 --builder-provider "
            "{mock|private}:Builder 身份是评估方可信主机输入,执行器对"
            "缺失 Provider fail closed(EXAM_INVALID),不存在默认 mock "
            "builder fallback",
            file=sys.stderr,
        )
        return 2

    ctx = load_exam_context(args.context)
    pack_path = str(Path(args.pack).resolve())
    retire_registry = args.retire_registry or str(
        Path(pack_path).parent / "retired_packs.json")
    attempt_registry = args.attempt_registry or str(
        Path(pack_path).parent / "attempt_registry.json")

    out, exit_code = run_sealed_exam(
        sealed_manifest_path=args.sealed_manifest,
        pack_path=pack_path,
        checkpoint_path=args.checkpoint,
        out_path=args.out,
        retire_registry_path=retire_registry,
        attempt_registry_path=attempt_registry,
        charter=ctx["charter"],
        schema=ctx["schema"],
        verdict_spec=ctx["verdict_spec"],
        eval_config=ctx["eval_config"],
        sandbox_profile=ctx.get("sandbox_profile"),
        # 工作包 A:issuer 不从 context 传入信任根;展示副本交给执行器
        # 与承诺做 canonical equality(不一致 -> EXAM_INVALID)
        context_issuer_payload=ctx.get("trusted_issuer_payload"),
        # 阶段 2.6.0f 工作包 A:评估方 Builder Identity Provider(显式
        # 传入;执行器对缺失/无效 Provider fail closed)
        builder_provider=builder_provider,
        detailed_path=args.detailed,
    )
    status = out.get("result", {}).get("status") or out.get("status")
    print(f"[hidden_exam_cli] 状态={status} 输出 -> {args.out}")
    if args.detailed and status == "EXAM_INVALID":
        print(
            "[hidden_exam_cli] 考试无效(EXAM_INVALID),无详细结果可公开,"
            "不退休考试包",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
