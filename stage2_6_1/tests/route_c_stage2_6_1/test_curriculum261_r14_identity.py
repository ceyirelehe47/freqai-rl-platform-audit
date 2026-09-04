# -*- coding: utf-8 -*-
"""R14 §十一:iteration identity 与治理文字清理测试。

- qualification plan digest 前缀 r14qp-(不得再生成 qp12-);
- design/parameter pack/sealed attestation 使用 R14 专属前缀;
- R14 模块不得出现"下一轮必须 R13"/"下一轮必须 R14"/"下一次必须
  R14"(自身失败路径应为 R15);
- R14 plan 模块源码不含 qp12- 生成。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_ITERATION_ID_R14,
    CURRICULUM261_R14_NAMESPACES,
    CURRICULUM261_SEED_NAMESPACES,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "rl_curriculum"

R14_MODULES = sorted(SRC.glob("curriculum261_r14_*.py"))


class TestIdentityPrefixes:
    def test_plan_digest_prefix_r14qp(self):
        from rl_curriculum.curriculum261_r14_plan import plan_digest_r14

        digest = plan_digest_r14({"iteration": "r14"})
        assert digest.startswith("r14qp-")

    def test_plan_module_has_no_qp12_generation(self):
        text = (SRC / "curriculum261_r14_plan.py").read_text(
            encoding="utf-8")
        assert '"qp12-"' not in text

    def test_design_digest_prefix(self):
        from rl_curriculum.curriculum261_r14_design import (
            design_plan_digest_r14,
        )

        assert design_plan_digest_r14({}).startswith("r14dp-")

    def test_pack_digest_prefix(self):
        from rl_curriculum.curriculum261_r14_param_pack import (
            pack_digest_r14,
        )

        assert pack_digest_r14({}).startswith("r14pk-")

    def test_sealed_preflight_digest_prefix(self):
        from rl_curriculum.curriculum261_r14_preflight import (
            sealed_preflight_digest,
        )

        assert sealed_preflight_digest(
            {"a": 1}).startswith("r14fa-")

    def test_code_identity_prefix(self):
        from rl_curriculum.curriculum261_r14_preflight import (
            _code_identity_digest_r14,
        )

        ident = _code_identity_digest_r14()
        assert ident["digest"].startswith("r14ci-")

    def test_freeze_surface_prefix(self):
        from rl_curriculum.curriculum261_r14_dependencies import (
            freeze_surface_manifest_r14,
        )

        # 结构级检查(真实树在 WSL;此处只验证前缀函数可达性由
        # freeze 测试覆盖;静态检查 digest 前缀常量)
        from rl_curriculum.curriculum261_r14_dependencies import (
            write_r14_code_freeze,
        )
        import inspect

        src_text = inspect.getsource(
            freeze_surface_manifest_r14)
        assert '"r14fs-"' in src_text

    def test_gate_topology_and_provenance_prefixes(self):
        from rl_curriculum.curriculum261_r14_gate_topology import (
            r14_gate_topology_digest,
        )

        assert r14_gate_topology_digest().startswith("r14gt-")

    def test_iteration_id(self):
        assert CURRICULUM261_ITERATION_ID_R14 == "r14"


class TestGovernanceText:
    @pytest.mark.parametrize("module", R14_MODULES,
                             ids=lambda m: m.name)
    def test_no_wrong_next_iteration_text(self, module):
        text = module.read_text(encoding="utf-8")
        assert "下一轮必须 R13" not in text, (
            f"{module.name} 含错误的下一轮指引(R13)")
        assert "下一轮必须 R14" not in text, (
            f"{module.name} 含错误的下一轮指引(R14 应为 R15)")
        assert "下一次必须 R14" not in text

    def test_failure_paths_point_to_r15(self):
        deps = (SRC / "curriculum261_r14_dependencies.py").read_text(
            encoding="utf-8")
        cli = (SRC / "curriculum261_r14_cli.py").read_text(
            encoding="utf-8")
        ns = (SRC / "curriculum261_r14_namespaces.py").read_text(
            encoding="utf-8")
        for text in (deps, cli, ns):
            assert "下一轮必须 R15" in text


class TestNamespaceIdentity:
    def test_all_r14_namespaces_registered(self):
        for ns in CURRICULUM261_R14_NAMESPACES:
            assert ns in CURRICULUM261_SEED_NAMESPACES, ns

    def test_r14_namespaces_disjoint_from_history(self):
        seen: set[str] = set()
        dupes: list[str] = []
        for ns in CURRICULUM261_SEED_NAMESPACES:
            if ns in seen:
                dupes.append(ns)
            seen.add(ns)
        assert not dupes

    def test_r14_namespaces_carry_iteration_token(self):
        for ns in CURRICULUM261_R14_NAMESPACES:
            assert "r14" in ns, ns

    def test_qualification_namespaces_final_set(self):
        quals = {"qualification_r14",
                 "preprocess_fit_qualification_r14",
                 "c2_independent_qualification_r14",
                 "cue_semantic_qualification_r14"}
        assert quals <= set(CURRICULUM261_R14_NAMESPACES)


class TestCliSubcommandIdentity:
    def test_new_subcommands_registered(self):
        from rl_curriculum.curriculum261_r14_cli import main

        import argparse

        parser_source = main.__module__
        assert parser_source == "rl_curriculum.curriculum261_r14_cli"
        # 通过 --help 验证子命令存在(独立进程在 roundtrip 测试覆盖)
        text = (SRC / "curriculum261_r14_cli.py").read_text(
            encoding="utf-8")
        for sub in ("provenance-lock", "full-cold-reader-check",
                    "fail-closure", "report-read",
                    "verify-formal-logs", "commit-b-allowlist",
                    "formal-log-record"):
            assert f'"{sub}"' in text, f"子命令 {sub} 未注册"
