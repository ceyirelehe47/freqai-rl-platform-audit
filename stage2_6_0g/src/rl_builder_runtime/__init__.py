"""Builder Runner 最小运行时(阶段 2.6.0g 收尾:工作包 B)。

与 rl_candidate_runtime 对称但**不同**的最小运行时:Builder Runner 的
挂载集合只有 builder staging(只读)+ tmpfs 输出目录,**没有**候选
checkpoint/sidecar bind-mount,也绝不授予任何候选可写目录读权限——
Builder 与 Candidate 使用不同的最小运行时和挂载集合(B2)。

本包被复制进匿名 staging 后在 unshare(user+mount+pid+proc+net)内
执行;逐文件内容哈希由 builder runtime manifest(builder-runtime-
manifest-v1,rtb- 前缀)绑定并进入 Builder Run Evidence。
"""

#: 运行时包版本(内容变化 = 新 manifest = 新 evidence 绑定)
RUNTIME_PACKAGE_VERSION = "rl-builder-runtime-1"
#: 沙箱内 Runner worker 的线协议(stdin 请求 / stdout 响应)
BUILDER_WORKER_PROTOCOL = "builder-runner-worker-v1"
#: Runner 运行时逐文件内容 manifest 格式(进入 Builder Run Evidence)
BUILDER_RUNTIME_MANIFEST_FORMAT = "builder-runtime-manifest-v1"
#: 本运行时必备文件(manifest 缺失即拒绝;同 B 语义)
REQUIRED_BUILDER_RUNTIME_FILES: tuple[str, ...] = (
    "__init__.py", "bootstrap.py", "runner.py",
)
