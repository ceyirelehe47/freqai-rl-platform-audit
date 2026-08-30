# -*- coding: utf-8 -*-
"""阶段 2.6.0f 兼容辅助:旧阶段测试调用 v6/v3 新 API 的统一默认参数。

- mock_builder_identity():MockBuilderIdentityProvider 派生身份(缓存);
- default_duration_contract():从 mock pack 派生的全局 duration
  contract(15m / 96 bars;缓存);
- verify_kwargs():verify_sealed_commitment 的增量 kwargs;
- validate_kwargs():validate_null_pack 的增量 kwargs。

旧阶段测试(2.6.0a-2.6.0e)的正例路径经由本辅助获得与 v7 执行器
一致的显式 Provider 与 duration contract;断言语义不降级。
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_IDENTITY = None
_CONTRACT = None


def mock_builder_identity():
    global _IDENTITY
    if _IDENTITY is None:
        from rl_curriculum.builder_identity import (
            MockBuilderIdentityProvider,
        )

        _IDENTITY = MockBuilderIdentityProvider().builder_identity()
    return _IDENTITY


def default_duration_contract():
    global _CONTRACT
    if _CONTRACT is None:
        from rl_curriculum.generators import FORMAL_NULL_FAMILIES
        from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack
        from rl_curriculum.null_duration_contract import (
            derive_global_null_duration_contract,
        )

        pack = build_mock_hidden_pack()
        _CONTRACT = derive_global_null_duration_contract(
            pack, required_families=list(FORMAL_NULL_FAMILIES))
    return _CONTRACT


def verify_kwargs() -> dict:
    """verify_sealed_commitment 的 v6 增量参数(显式 Provider + 合同)。"""
    return {
        "builder_identity": mock_builder_identity(),
        "duration_contract": default_duration_contract(),
    }


def validate_kwargs() -> dict:
    """validate_null_pack 的 v3 增量参数。"""
    return {
        "builder_identity": mock_builder_identity(),
        "duration_contract": default_duration_contract(),
    }
