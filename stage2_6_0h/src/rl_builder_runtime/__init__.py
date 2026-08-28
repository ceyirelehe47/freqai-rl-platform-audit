"""最小 Builder 运行时(阶段 2.6.0h:builder-runner-worker-v2)。

与 rl_candidate_runtime 对称但挂载集合不同:无 checkpoint/sidecar
bind-mount;阶段 2.6.0h 起 sandbox 进一步升级为 pivot_root 最小
rootfs + 私有最小 /dev + Landlock /proc 最小文件集 + seccomp 进程树
策略(子进程/exec 全禁;仅允许 CLONE_THREAD 线程)。
"""

RUNTIME_PACKAGE_VERSION = "rl-builder-runtime-2"
BUILDER_WORKER_PROTOCOL = "builder-runner-worker-v2"
BUILDER_RUNTIME_MANIFEST_FORMAT = "builder-runtime-manifest-v1"
REQUIRED_BUILDER_RUNTIME_FILES = (
    "__init__.py",
    "bootstrap.py",
    "runner.py",
)

#: 私有最小 /dev 的设备节点白名单(B1:宿主 /dev/dev/shm 整体不可见)
PRIVATE_DEV_NODES = ("null", "zero", "urandom", "random", "full")
#: Builder 允许读取的 /proc 最小文件集(B2:C1 沙箱报告实测来源)
PROC_MINIMAL_FILES = (
    "/proc/self/status",
    "/proc/self/maps",
    "/proc/self/mountinfo",
    "/proc/self/net/dev",
)
