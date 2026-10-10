# COMMANDS APPENDIX — A2 RuntimeClosure(qaf_v3 未来一次性执行;批准后使用)

固定值:Commit A=`0735f2559aa80889bfed16c88d20e5c72c280a75`(tree `b5e719ff067295fb202c75cb10f1a09879084eca`) |
P3=`/home/cryptorl/projects/crypto_rl_qaf_v3` |
D3=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3` |
PIN=`/home/cryptorl/release_pin_qaf_v3`(只读候选 clone,**branch route-c-stage2-6-1-repair17 @ Commit A=0735f2559aa80889bfed16c88d20e5c72c280a75;不得 detach/pull——ancestry 分支名检查与 HEAD==A 冻结检查会拒绝) |
REPO=`/mnt/f/trading/freqai-rl-audit` |
计划(qbpl)=`qbpl-aaa1d6d9595f649efe8925a2fb17a0a5cb61d11004a72cd6395e48f7de0b103d` |
record=`…/a2_runtime_closure_v1/evidence/regress261_d3/regression_evidence_v3_record.json`(sha256 `1022baae5cc5f44050d31f69ce481de581f5e403c982f820fc85ed7445f9a81b`) |
PY=`/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python` |
PREP=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3/prep_qaf_v3`(批准原件落点=普通目录)

## E1. 部署配置激活(自准备域候选副本;仅批准轮)

```sh
cp $REPO/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/config_candidate/qprod_deploy_config_candidate.json \
   $D3/qprod_deploy_config.json
```

## E2. 前置安装 + 同源复核(operator prepare;幂等)

```sh
cd $P3 && PYTHONDONTWRITEBYTECODE=1 $PY $P3/stage2_6_1_runner/qaf_v2_operator_entry.py prepare \
  --repo $REPO --deploy-root $D3 --project-dir $P3 --attempt qaf_v3
# 期望:install 幂等 + same_source_verify ok(r17gtrec-3112e5de…)
```

注意:P3/D3/PIN 三面部署与运行依赖前置(本附录外的实装面)已由本轮完成并在
`evidence/runtime_verify/`(preflight_P3 ok=true + freeze_engineering_P3 + prefix_probe_fr1_0735f255 活链前缀 3 步全绿(上轮 prefix_probe_0f494d27 同名留档) + substance 同根 rc0/错根 rc2)+ `evidence/three_way_compare.json`
(699/598/661 全等,meta 绑定 0735f255)留档;operator execute 的 runtime_dependencies 检查(含 pin HEAD==A、freeze 路径 clean、
三面 vs 候选 CR 投影、已接受原件字节)在首一次性写前强制执行(E1 未装时全门 fail-closed,已实测)。

## E3. 批准原件构造(用户提供批准原文后)

同 v2 轮合同:`formal_approval_digest`;approved 10 键(roots=D3 三根、`coordinate_ids=[]`、
`authorized_stop_after="verify-formal-logs"`、`model_update_authorized=true`、quota=计划 quota、
namespaces=`qaf_input_scope_for_attempt("qaf_v3")` 26 名、`code_freeze_sha`=0735f2559aa80889bfed16c88d20e5c72c280a75、
`research_plan_digest`=qbpl-aaa1d6d9595f649efe8925a2fb17a0a5cb61d11004a72cd6395e48f7de0b103d);`approval_source={"kind":"user_direct_approval","statement_digest":<原文sha256>,…}`。
写 `$PREP/approval_qaf_v3.json`(mkdir -p $PREP)。authorization 文案从最终已校验批准生成,不手抄摘要。

## E4. 一次性执行(operator execute;前置=E1-E3 已完成)

```sh
cd $P3 && PYTHONDONTWRITEBYTECODE=1 $PY $P3/stage2_6_1_runner/qaf_v2_operator_entry.py execute \
  --repo $REPO \
  --deploy-root $D3 --project-dir $P3 \
  --approval-json $PREP/approval_qaf_v3.json \
  --regression-evidence $REPO/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/evidence/regress261_d3/regression_evidence_v3_record.json \
  --admission-id qaf-v3-0735f255-a2 \
  --authorization "<批准原文引用 + statement sha256>" \
  --plan-digest b5e719ff067295fb202c75cb10f1a09879084eca --plan-digest-method git_tree_digest \
  --code-freeze-sha 0735f2559aa80889bfed16c88d20e5c72c280a75 \
  --stop-after verify-formal-logs --model-update --attempt qaf_v3
```

注意:禁止手动 export R17/QProd 根重定向环境变量;禁止 `--sentinel-before-chain`(真实根);
中断/回执缺失/重复调用:入口先查在场原件与消费账,受控拒绝,不盲目重试;
失败封口政策不变(零业务/禁新代码/下一轮全新 namespace)。
