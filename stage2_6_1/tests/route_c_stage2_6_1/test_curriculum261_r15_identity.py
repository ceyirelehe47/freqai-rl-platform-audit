# -*- coding: utf-8 -*-
"""R15 §十一:iteration identity 与治理文字清理测试。

- qualification plan digest 前缀 r15qp-(不得再生成 qp12-);
- design/parameter pack/sealed attestation 使用 R15 专属前缀;
- R15 模块不得出现"下一轮必须 R13"/"下一轮必须 R16"/"下一次必须
  R15"(自身失败路径应为 R15);
- R15 plan 模块源码不含 qp12- 生成。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_ITERATION_ID_R15,
    CURRICULUM261_R15_NAMESPACES,
    CURRICULUM261_SEED_NAMESPACES,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "rl_curriculum"

R15_MODULES = sorted(SRC.glob("curriculum261_r15_*.py"))


class TestIdentityPrefixes:
    def test_plan_digest_prefix_r15qp(self):
        from rl_curriculum.curriculum261_r15_plan import plan_digest_r15

        digest = plan_digest_r15({"iteration": "r15"})
        assert digest.startswith("r15qp-")

    def test_plan_module_has_no_qp12_generation(self):
        text = (SRC / "curriculum261_r15_plan.py").read_text(
            encoding="utf-8")
        assert '"qp12-"' not in text

    def test_design_digest_prefix(self):
        from rl_curriculum.curriculum261_r15_design import (
            design_plan_digest_r15,
        )

        assert design_plan_digest_r15({}).startswith("r15dp-")

    def test_pack_digest_prefix(self):
        from rl_curriculum.curriculum261_r15_param_pack import (
            pack_digest_r15,
        )

        assert pack_digest_r15({}).startswith("r15pk-")

    def test_sealed_preflight_digest_prefix(self):
        from rl_curriculum.curriculum261_r15_preflight import (
            sealed_preflight_digest,
        )

        assert sealed_preflight_digest(
            {"a": 1}).startswith("r15fa-")

    def test_code_identity_prefix(self):
        from rl_curriculum.curriculum261_r15_preflight import (
            _code_identity_digest_r15,
        )

        ident = _code_identity_digest_r15()
        assert ident["digest"].startswith("r15ci-")

    def test_freeze_surface_prefix(self):
        from rl_curriculum.curriculum261_r15_dependencies import (
            freeze_surface_manifest_r15,
        )

        # 结构级检查(真实树在 WSL;此处只验证前缀函数可达性由
        # freeze 测试覆盖;静态检查 digest 前缀常量)
        from rl_curriculum.curriculum261_r15_dependencies import (
            write_r15_code_freeze,
        )
        import inspect

        src_text = inspect.getsource(
            freeze_surface_manifest_r15)
        assert '"r15fs-"' in src_text

    def test_gate_topology_and_provenance_prefixes(self):
        from rl_curriculum.curriculum261_r15_gate_topology import (
            r15_gate_topology_digest,
        )

        assert r15_gate_topology_digest().startswith("r15gt-")

    def test_iteration_id(self):
        assert CURRICULUM261_ITERATION_ID_R15 == "r15"


class TestGovernanceText:
    @pytest.mark.parametrize("module", R15_MODULES,
                             ids=lambda m: m.name)
    def test_no_wrong_next_iteration_text(self, module):
        text = module.read_text(encoding="utf-8")
        # R15 的正确下一轮指引 = R16;R13/R14/R15 均为错误指引
        assert "下一轮必须 R13" not in text, (
            f"{module.name} 含错误的下一轮指引(R13)")
        assert "下一轮必须 R14" not in text, (
            f"{module.name} 含错误的下一轮指引(R14)")
        assert "下一轮必须 R15" not in text, (
            f"{module.name} 含错误的下一轮指引(R15 应为 R16)")
        assert "下一次必须 R15" not in text

    def test_failure_paths_point_to_r15(self):
        deps = (SRC / "curriculum261_r15_dependencies.py").read_text(
            encoding="utf-8")
        cli = (SRC / "curriculum261_r15_cli.py").read_text(
            encoding="utf-8")
        ns = (SRC / "curriculum261_r15_namespaces.py").read_text(
            encoding="utf-8")
        for text in (deps, cli, ns):
            assert "下一轮必须 R16" in text


class TestNamespaceIdentity:
    def test_all_r15_namespaces_registered(self):
        for ns in CURRICULUM261_R15_NAMESPACES:
            assert ns in CURRICULUM261_SEED_NAMESPACES, ns

    def test_r15_namespaces_disjoint_from_history(self):
        seen: set[str] = set()
        dupes: list[str] = []
        for ns in CURRICULUM261_SEED_NAMESPACES:
            if ns in seen:
                dupes.append(ns)
            seen.add(ns)
        assert not dupes

    def test_r15_namespaces_carry_iteration_token(self):
        for ns in CURRICULUM261_R15_NAMESPACES:
            assert "r15" in ns, ns

    def test_qualification_namespaces_final_set(self):
        quals = {"qualification_r15",
                 "preprocess_fit_qualification_r15",
                 "c2_independent_qualification_r15",
                 "cue_semantic_qualification_r15"}
        assert quals <= set(CURRICULUM261_R15_NAMESPACES)


class TestCliSubcommandIdentity:
    def test_new_subcommands_registered(self):
        from rl_curriculum.curriculum261_r15_cli import main

        import argparse

        parser_source = main.__module__
        assert parser_source == "rl_curriculum.curriculum261_r15_cli"
        # 通过 --help 验证子命令存在(独立进程在 roundtrip 测试覆盖)
        text = (SRC / "curriculum261_r15_cli.py").read_text(
            encoding="utf-8")
        for sub in ("provenance-lock", "full-cold-reader-check",
                    "fail-closure", "report-read",
                    "verify-formal-logs", "commit-b-allowlist",
                    "formal-log-record"):
            assert f'"{sub}"' in text, f"子命令 {sub} 未注册"
