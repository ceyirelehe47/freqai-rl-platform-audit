"""最小 Builder 运行时(阶段 2.6.0j:builder-runner-worker-v4)。

2.6.0j 语义(在 0i 密闭确定性输入之上升级为不可逆密封计算):
- Worker 的整个只读根文件系统是**内容寻址 runtime bundle**(rbm-
  manifest;bootstrap 在 pivot 后、exec 前对实际挂载内容全量复验);
- 无 /proc、无 /usr、无宿主 conda 活树;/dev 无真实 random/urandom,
  只有确定性虚拟熵源(受承诺字节)与 null/zero/full;
- Prepare:v2 filter(arch/x32/进程/时钟/熵)+vDSO 冻结 stub +
  PR_SET_TSC(SIGSEGV)+native allowlist 预加载 + builder 包顶层
  纯度 AST 验证 + 导入闭包逐文件绑定 bundle manifest(**全部在
  build 之前完成**);
- Seal(ACK 后不可逆):PR_SET_MDWE(REFUSE_EXEC_GAIN) -> fd 隔离
  (stdin 关闭、1/2 -> /dev/null、真实管道仅存 RESULT_FD=87) ->
  final compute filter(**default deny** + 最小 allowlist + write/
  mmap/mprotect/rt_sigaction 参数过滤;prctl 被拒 -> PR_TSC_ENABLE
  无法重新开启 TSC);
- Compute:build_pack 纯计算(未知 syscall 一律 EPERM;open/stat/
  statfs/sysinfo/getcpu/uname/getrandom/clock/PROT_EXEC/线程/进程
  全拒);sealed compute report v2 + 运行时锁 v4。
"""

RUNTIME_PACKAGE_VERSION = "rl-builder-runtime-4"
BUILDER_WORKER_PROTOCOL = "builder-runner-worker-v4"
BUILDER_RUNTIME_MANIFEST_FORMAT = "builder-runtime-manifest-v1"
REQUIRED_BUILDER_RUNTIME_FILES = (
    "__init__.py",
    "bootstrap.py",
    "bundle.py",
    "runner.py",
    "sealed_compute.py",
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
