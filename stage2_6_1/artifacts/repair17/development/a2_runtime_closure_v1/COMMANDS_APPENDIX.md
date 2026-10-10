# COMMANDS APPENDIX — A2 RuntimeClosure(qaf_v3 未来一次性执行;批准后使用)

固定值:Commit A=`c0fb685823eb4733bda9f5920601311228d55fde`(tree `a2621f8e9843aecac7d99bc85377e30d91d90b0f`) |
P3=`/home/cryptorl/projects/crypto_rl_qaf_v3` |
D3=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3` |
PIN=`/home/cryptorl/release_pin_qaf_v3`(只读候选 clone,**branch route-c-stage2-6-1-repair17 @ Commit A=c0fb685823eb4733bda9f5920601311228d55fde;不得 detach/pull——ancestry 分支名检查与 HEAD==A 冻结检查会拒绝) |
REPO=`/mnt/f/trading/freqai-rl-audit` |
计划(qbpl)=`qbpl-5963af98aca388afbbe8a9088da70a26a556ee31096186f12d53c44dbf1145fd` |
record=`…/a2_runtime_closure_v1/evidence/regress261_d3/regression_evidence_v3_record.json`(sha256 `007baaf328b2bfe948784c016f51b934dfea5a211fbba2eab5cef3798ef04fc4`) |
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
`evidence/runtime_verify/`(preflight_P3 ok=true + freeze_engineering_P3 + prefix_probe_fr2_c0fb6858 活链前缀 3 步全绿(上轮 prefix_probe_0f494d27 同名留档) + substance 同根 rc0/错根 rc2)+ `evidence/three_way_compare.json`
(700/599/662 全等,meta 绑定 c0fb6858)留档;operator execute 的 runtime_dependencies 检查(含 pin HEAD==A、freeze 路径 clean、
三面 vs 候选 CR 投影、已接受原件字节)在首一次性写前强制执行(E1 未装时全门 fail-closed,已实测)。

## E3. 批准原件构造(用户提供批准原文后)

同 v2 轮合同:`formal_approval_digest`;approved 10 键(roots=D3 三根、`coordinate_ids=[]`、
`authorized_stop_after="verify-formal-logs"`、`model_update_authorized=true`、quota=计划 quota、
namespaces=`qaf_input_scope_for_attempt("qaf_v3")` 26 名、`code_freeze_sha`=c0fb685823eb4733bda9f5920601311228d55fde、
`research_plan_digest`=qbpl-5963af98aca388afbbe8a9088da70a26a556ee31096186f12d53c44dbf1145fd);`approval_source={"kind":"user_direct_approval","statement_digest":<原文sha256>,…}`。
写 `$PREP/approval_qaf_v3.json`(mkdir -p $PREP)。authorization 文案从最终已校验批准生成,不手抄摘要。

## E4. 一次性执行(operator execute;前置=E1-E3 已完成)

```sh
cd $P3 && PYTHONDONTWRITEBYTECODE=1 $PY $P3/stage2_6_1_runner/qaf_v2_operator_entry.py execute \
  --repo $REPO \
  --deploy-root $D3 --project-dir $P3 \
  --approval-json $PREP/approval_qaf_v3.json \
  --regression-evidence $REPO/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/evidence/regress261_d3/regression_evidence_v3_record.json \
  --admission-id qaf-v3-c0fb6858-a2 \
  --authorization "<批准原文引用 + statement sha256>" \
  --plan-digest a2621f8e9843aecac7d99bc85377e30d91d90b0f --plan-digest-method git_tree_digest \
  --code-freeze-sha c0fb685823eb4733bda9f5920601311228d55fde \
  --stop-after verify-formal-logs --model-update --attempt qaf_v3
```

注意:禁止手动 export R17/QProd 根重定向环境变量;禁止 `--sentinel-before-chain`(真实根);
中断/回执缺失/重复调用:入口先查在场原件与消费账,受控拒绝,不盲目重试;
失败封口政策不变(零业务/禁新代码/下一轮全新 namespace)。
