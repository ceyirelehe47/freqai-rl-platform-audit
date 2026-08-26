# 沙箱能力矩阵(WSL CryptoRL-Ubuntu-24.04)

- 检查时间: 2026-08-26T12:02:34Z
- 内核: 6.18.33.2-microsoft-standard-WSL2
- unshare 二进制: True
- user+mount+pid+proc+net namespace 组合: True
- tmpfs 挂载: True
- 只读 bind mount: True
- 空 netns(仅 loopback): True
- Landlock ABI: v4
- PR_SET_NO_NEW_PRIVS: True
- **系统级沙箱可用: True**

## 隔离层

| 层 | 机制 | 验证 |
|---|---|---|

| 文件系统 | Landlock deny-by-default + 只读 bind | sandbox_denial_trace.json |

| PID/proc | 独立 PID ns + 新 procfs | sandbox_proc_isolation.json |

| 网络 | 独立 netns(仅 down lo,无路由无 DNS) | sandbox_network_test.json |

| checkpoint | staging 副本 + remount ro + Landlock 无写权 | sandbox_denial_trace.json |

| 资源 | RLIMIT CPU/AS/FSIZE/NOFILE/NPROC | sandbox_resource_limits.json |

| 协议 | 单步超时/stdout 行长上限/非法输出 fail closed | 测试套件 |
