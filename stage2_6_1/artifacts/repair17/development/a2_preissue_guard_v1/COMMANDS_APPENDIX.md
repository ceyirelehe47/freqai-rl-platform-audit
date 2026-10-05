# A2-R2 未来一次性执行命令附录(批准后使用;本轮未执行)

固定值:Commit A=`a96bedea24b3a84a19d30f505a121d8c3d68bba3` |
P2=`/home/cryptorl/projects/crypto_rl_qaf_v2` |
D2=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2` |
REPO=`/mnt/f/trading/freqai-rl-audit` |
计划=`qbpl-4c654375cec2c20070816c75d0980b3ff50087e67364d50ad0cb6a4a6d4a77f5` |
tree digest=`863ab24c72b19296d58790b4bbd5b2fa8e163f58` |
record=`…/a2_preissue_guard_v1/evidence/regress261_d2/regression_evidence_v3_record.json`(sha256 `ac3ff15083c0dee5…`) |
PY=`/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python` |
PREP=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2/prep_qaf_v2`(批准原件落点=普通目录,guard/freshness 不扫描;勿写 A artifact 根)

## E1. 部署配置激活(自准备域候选副本;仅批准轮)

```sh
cp $REPO/stage2_6_1/artifacts/repair17/development/a2_preissue_guard_v1/config_candidate/qprod_deploy_config_candidate.json \
   $D2/qprod_deploy_config.json
```

## E2. 前置安装 + 同源复核(operator prepare;幂等,可重复)

```sh
cd $P2 && PYTHONDONTWRITEBYTECODE=1 $PY $P2/stage2_6_1_runner/qaf_v2_operator_entry.py prepare \
  --repo $REPO --deploy-root $D2 --project-dir $P2 --attempt qaf_v2
# 期望:install 幂等 + same_source_verify ok:true(r17gtrec-3112e5de…)
```

## E3. 批准原件构造(用户提供批准原文后;digest 绑定)

按 FFAB v1 批准轮同形(模块 `curriculum261_qprod_formal.formal_approval_digest`;
`namespaces`=QAF2 26 名(经 `qaf_input_scope_for_attempt("qaf_v2")`);
`quota`=计划 payload.quota;roots=D2 三根;stop=verify-formal-logs;model_update=true;
`approval_source.statement_digest`=批准原文 sha256)。写 `$PREP/approval_qaf_v2.json`(先 mkdir -p $PREP)。

## E4. 一次性执行(operator execute;**前置要求 E1-E3 已完成**:execute 要求安装目标已就绪(preissue 门核验,不自动执行 E2);其自动完成的部分=环境白名单→preissue 门→批准↔参数绑定门→已存状态/证据预检→authority init→record-approval→issue-permit→prereg→admission→launch。E1 配置激活、E2 prepare 安装、E3 批准原件构造是操作员手动前置步;已完成 E2 时幂等可复核):
## 环境白名单→preissue 硬门→authority init→record-approval→
## issue-permit(守卫)→prereg→admission(守卫)→launch(A2 双参数)→收尾)

```sh
cd $P2 && PYTHONDONTWRITEBYTECODE=1 $PY $P2/stage2_6_1_runner/qaf_v2_operator_entry.py execute \
  --repo $REPO \
  --deploy-root $D2 --project-dir $P2 \
  --approval-json $PREP/approval_qaf_v2.json \
  --regression-evidence $REPO/stage2_6_1/artifacts/repair17/development/a2_preissue_guard_v1/evidence/regress261_d2/regression_evidence_v3_record.json \
  --admission-id qaf-v2-a96bedea-a2 \
  --authorization "<批准原文引用 + statement sha256>" \
  --plan-digest 863ab24c72b19296d58790b4bbd5b2fa8e163f58 \
  --plan-digest-method git_tree_digest \
  --code-freeze-sha a96bedea24b3a84a19d30f505a121d8c3d68bba3 \
  --stop-after verify-formal-logs --model-update --attempt qaf_v2
```

注意:
- 禁止手动 export R17/QProd 根重定向环境变量(入口自装;在场即拒)。
- 禁止 `--sentinel-before-chain`(真实根;入口已拒)。
- 中断/回执缺失/重复调用:入口先查在场原件与消费账,受控拒绝,不盲目重试。
- 失败封口政策不变:零业务/禁新代码/下一轮全新 namespace。
