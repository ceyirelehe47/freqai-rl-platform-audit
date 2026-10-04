# 控制流:操作员入口 → 两 issuer → launch → workflow 首步(候选 513e75e3)

文本调用图(锁/检查/写/消费/异常;无新 schema):

```
qaf_v2_operator_entry.py(操作员唯一受控入口)
├─ check   只读:resolve 根(config formal_roots→harden_root 真实路径/保护根拒)
│          + install 检验 + freshness(fresh 字段;rc 不单独作就绪结论)
│          + 同源 verifier(project_dir=全模块树)→ 报告可写独立证据目录
├─ prepare 幂等安装:read_pinned_source(钉死 git 对象 de81aba2:
│          json sha 9af55175…/digest cde2b72a…/内容 r17gtrec-3112e5de…)
│          → install_to_target(同字节幂等/异物/半写拒)
│          + same_source_verify(目标实文件重算)
└─ execute 串行受控(每步写前查在场;不盲重试):
   1 env 白名单(拒手动 R17/QProd 根重定向)
   2 preissue 硬门(guard.preissue_gate:源/目标/同源/新鲜度)
   2b 批准↔调用参数绑定门(RC gate1 F1;首一次性写前):
     批准原件解析 → --plan-digest == 候选 tree digest 重算 →
     build_formal_level_a_plan+research_plan_digest+
     validate_formal_approval(逐项:freeze/三根/范围/quota/
     stop/model_update);不符零写拒(rc=96)
   3 authority init ──────────── O_EXCL 创建 authority_identity.json
     (并发败者:正式身份→already(rc0)/异物→rc1)
   4 record-approval(用户原文)── O_EXCL 创建批准原件
   5 issue-permit ────────────── 先 preissue 门(qaf_v2 无条件),
     再 O_EXCL 创建 qprod_permit_level_a_qprod_a_formal_v2.json
     (RC04 修复:原 check→write TOCTOU 已消除)
   6 prereg 落盘(计划 digest=Commit A tree、record、state root)
   7 admission 签发(r17_admission_issue):
     · prereg.iteration→QAF_ATTEMPTS 派生守卫(缺/错配/未登记迭代拒)
     · substance verify 子进程(真实 record 核验;错根拒)
     · O_EXCL 创建 .r17_formal_admission.json + append issuance log
   8 launch(qprod_formal_level_a_entry launch):
     · 门禁:admission 在场+freeze 绑定;A2 双参数强制;
       哨兵仅测试域;env 白名单;漂移重查(permit 消费前重验目标)
     · 子进程 env 显式构造(_child_argv_and_env):
       PYTHONPATH=P2/src + DEPLOYED_STATE_ROOT=D2 state,
       剥 R17/QPROD 根重定向
     · A2(stop=verify-formal-logs)→ r17_cli chain-run
       ├ storage 天花板 → formal admission 闸门(消费)
       ├ R17ChainSession.acquire(唯一会话锁)
       ├ build_workflow_plan_r17(formal, attempt=qaf_v2)
       ├ chain 预算门(write_chain_budget_gate)
       └ execute_workflow_chain_r17:
          步1 provenance-verify(读安装目标,重算==落盘 digest)
          → …科学叶(按批准预算门控)…
          → verify-formal-logs 只读收口
          失败→fail-closure→iteration_aborted→release(fail closed)
```

一次性资源与写序:init/批准/permit/admission 均 O_EXCL 单写;
会话锁保证同 state 根唯一链;许可消费=admission 闸门通过即记账;
中断/未知回执→重查在场原件与消费账,受控拒绝,不重试不回收。

替身边界(测试):仅"一次性资源落点=pytest 临时域"与
RC05 停止边界值;issuer/validator/workflow/执行器全真实。
