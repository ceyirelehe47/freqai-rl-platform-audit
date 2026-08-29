"""最小 Builder 运行时(阶段 2.6.0i:builder-runner-worker-v3)。

2.6.0i 语义(在 0h pivot_root 最小 rootfs 之上升级为密闭确定性输入):
- Worker 的整个只读根文件系统是**内容寻址 runtime bundle**(rbm-
  manifest;bootstrap 在 pivot 后、exec 前对实际挂载内容全量复验);
- 无 /proc、无 /usr、无宿主 conda 活树;/dev 无真实 random/urandom,
  只有确定性虚拟熵源(受承诺字节)与 null/zero/full;
- seccomp v2:arch 必须是 AUDIT_ARCH_X86_64,x32 bit 显式拒绝,进程
  创建(fork/vfork/clone/clone3/exec)全拒(**clone 不再放行
  CLONE_THREAD:正式 Builder 禁止一切线程**),clock/getrandom/熵
  syscall 全拒;
- vDSO 时钟页 munmap(真实系统时间不可观察)+ PR_SET_TSC(SIGSEGV);
- 运行时锁 v3:实际导入逐模块绑定 bundle manifest(文件字节 + 归属
  by-path),native 绑定与线程静止证明由 Supervisor 在 quiesce 时刻
  从外部 /proc 实测合并。
"""

RUNTIME_PACKAGE_VERSION = "rl-builder-runtime-3"
BUILDER_WORKER_PROTOCOL = "builder-runner-worker-v3"
BUILDER_RUNTIME_MANIFEST_FORMAT = "builder-runtime-manifest-v1"
REQUIRED_BUILDER_RUNTIME_FILES = (
    "__init__.py",
    "bootstrap.py",
    "bundle.py",
    "runner.py",
)

#: 私有最小 /dev 设备节点(2.6.0i:**不含** urandom/random——真实熵源
#: 设备不存在;/dev/urandom 与 /dev/random 是 dev-internal 下受承诺
#: 确定性字节文件的只读 bind)
PRIVATE_DEV_NODES = ("null", "zero", "full")

#: Builder 可读取的 /proc 最小文件集(2.6.0i:空——/proc 完全不挂载,
#: 动态内核状态对 Builder 不可观察;Supervisor 侧外部实测)
PROC_MINIMAL_FILES = ()

#: Worker 内的固定 hostname(UTS namespace)
BUILDER_WORKER_HOSTNAME = "builder-worker"
