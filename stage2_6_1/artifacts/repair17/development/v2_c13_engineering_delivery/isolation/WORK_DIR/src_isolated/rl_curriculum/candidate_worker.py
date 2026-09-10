"""阶段 2.6.0b:候选 worker 协议宿主(历史模块,正式路径已迁移)。

阶段 2.6.0a 的本模块实现了普通 JSON-lines 子进程候选
(SubprocessCandidate)。阶段 2.6.0b 工作包 C 判定它只是 API 隔离,
不是正式安全边界:候选与评估主进程共享文件系统/PID/网络/当前用户
权限。正式执行路径已迁移到:

- rl_candidate_runtime.worker(最小候选运行时,沙箱内执行);
- rl_curriculum.sandbox.SandboxedCandidate(unshare namespaces +
  Landlock + rlimits 的系统级沙箱启动器)。

本模块保留 scrub_environment(沙箱启动器复用的环境清洗工具)与协议
版本常量;SubprocessCandidate 已删除——正式 CLI 不存在
--no-subprocess,普通子进程不再是可用的正式执行形态。
"""

from __future__ import annotations

import os

#: 候选 worker 协议版本(reset 无任何 Episode 身份 token;见
#: rl_candidate_runtime.worker)。旧 candidate-worker-v1 携带
#: derived_seed,已被 v2 取代。
WORKER_PROTOCOL = "candidate-worker-v2"

# 启动环境清洗:移除可能携带考试信息的变量名模式(白名单思路:
# 只保留运行时必需变量,凡命中模式的一律删除)
_ENV_DENY_PATTERNS: tuple[str, ...] = (
    "SEED", "FAMILY", "SPLIT", "PACK", "EXAM", "CHARTER", "HIDDEN",
    "PARAMS", "NULL", "VERDICT",
)


def scrub_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """清洗子进程环境:删除命中泄漏模式的变量(值也不复制)。"""
    base = dict(env if env is not None else os.environ)
    scrubbed = {}
    for key, value in base.items():
        if any(pat in key.upper() for pat in _ENV_DENY_PATTERNS):
            continue
        scrubbed[key] = value
    return scrubbed
