"""阶段 2.6.1 测试夹具:C1/C2/C3 课程生成器与资格闭环。"""

from __future__ import annotations

import os

# WP1(fc-integrity):BLAS/OpenMP 线程池在 pytest 进程内是未屏蔽
# TERM/INT 的 C 层线程(/proc 可见、threading.enumerate 不可见),
# 会使直调形态 supervisor 的截止点前提核验如实失败(rc=7)。
# 生产 supervisor 独立进程不导入 numpy,无此线程面;此处仅约束
# 测试进程的第三方数值库线程池(在 numpy 首次 import 前生效),
# 不修改生产开关、不 patch 前提函数——被测的 residual/保护/发布
# 语义照常执行。
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
           "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

# v2 轮(S3 全量回归归因):torch 在 WSL GPU 直通可用时 import 即
# 初始化 CUDA 事件/autograd 线程(cuda-EvtHandlr/pt_autograd_0/
# cuda*),同为未屏蔽 C 层线程,同样使 supervisor 截止点核验按
# 控制能力失效终结(rc=7)。测试面零 GPU 依赖(curriculum261_smoke
# 显式 device="cpu"),屏蔽 CUDA 与上面的 BLAS 缓解同性质:只约束
# 测试进程的第三方线程面,不改生产开关。
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# v3 轮(2026-09-25):session 级共享真实完整回归运行。合法完整
# 证据必须来自真实执行器产物;一次构建,全部 substance/e2e 测试
# 复用(run 目录只读;签发/消费 e2e 各自清理许可副作用)。
import pytest


@pytest.fixture(scope="session")
def r17_canonical_full_run(tmp_path_factory):
    from types import SimpleNamespace
    from r17_admission_substance_test_support import (
        git_repo_with_candidate, run_executor, sync_deploy_surface,
        record_path)
    base = tmp_path_factory.mktemp("r17_canonical_full_run")
    repo, commit_a, parent = git_repo_with_candidate(base)
    deploy = base / "deploy"
    sync_deploy_surface(repo, commit_a, deploy)
    run_dir, summary, rc = run_executor(
        base / "run", repo, commit_a, deploy, expect_rc=(0,))
    assert rc == 0 and summary.get("ok"), summary
    return SimpleNamespace(
        base=base, repo=repo, commit_a=commit_a, parent=parent,
        deploy=deploy, run_dir=run_dir, record=record_path(run_dir),
        summary=summary)
