"""最小候选运行时包(阶段 2.6.0b 工作包 C6)。

本包是候选沙箱内唯一可见的项目代码:只包含
- candidate worker 协议(JSON-lines;reset 无任何 Episode 身份 token);
- checkpoint sidecar 守卫(SHA-256/规范版本/章程/observation 绑定);
- 沙箱 bootstrap(mount namespace 布置 + Landlock 规则 + rlimits + exec)。

不包含(且永远不得加入):generators / exam_pack / formal_exam /
sealed_exam / verdict_spec / evaluator 等评估与考试代码。

公开仓库包含本包全部源码(mock 沙箱 profile 的一部分)。
"""

WORKER_PROTOCOL = "candidate-worker-v2"
RUNTIME_PACKAGE_VERSION = "rl-candidate-runtime-stage2_6_0c-v1"
