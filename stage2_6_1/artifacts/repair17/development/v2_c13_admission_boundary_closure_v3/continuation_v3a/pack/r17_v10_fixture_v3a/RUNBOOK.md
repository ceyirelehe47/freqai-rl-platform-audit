# Agent 执行 Runbook

本包仅补 pipeline 测试夹具；旧 v3 九文件已应用并提交，不再重复应用。

## 1. 接手、SHA 与单文件应用

```bash
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
REPO=/mnt/f/trading/freqai-rl-audit
DEPLOY=/home/cryptorl/projects/crypto_rl
PACK=/实际解压位置/r17_v10_fixture_v3a
BASE=1ea193c0f1eb710e37aa23aa89f261617eb93c43
WORK="$DEPLOY/work/R17V10Fixture-v3a_$(date -u +%Y%m%dT%H%M%SZ)"
test ! -e "$WORK"
mkdir -p "$WORK"
cd "$REPO"
git fetch origin
test "$(git branch --show-current)" = route-c-stage2-6-1-repair17
test "$(git rev-parse HEAD)" = "$BASE"
test "$(git rev-parse origin/route-c-stage2-6-1-repair17)" = "$BASE"
git status --porcelain=v1 > "$WORK/status_before.txt"
git log --oneline -8 > "$WORK/commits_before.txt"
git ls-remote origin refs/heads/route-c-stage2-6-1-repair17 > "$WORK/remote_before.txt"
```

按任务书保存只读区/锁/claim 字节快照。允许已知活动监护日志追加单独记账；其他未知更改停止。

```bash
cd "$PACK"
sha256sum -c SHA256SUMS
python tools/apply_fixture_patch.py --repo "$REPO" \
  > "$WORK/apply_check.json" 2> "$WORK/apply_check.stderr.log"
# 必须先记录、检查 rc=0，才执行下一条。
python tools/apply_fixture_patch.py --repo "$REPO" --apply --recovery "$WORK/apply_recovery" \
  > "$WORK/apply.json" 2> "$WORK/apply.stderr.log"
cd "$REPO"
git diff --check
git diff --name-only
git diff -- stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py
```

应用及 Git diff 各命令保存实际 rc。只允许一个测试文件变更，原测试体未改，新增五个 case。生产源码/十成员治理 lock/历史 lock 必须与 BASE 一致。不得 relock。

## 2. 同步与一次定向八文件

```bash
cd "$REPO"
bash stage2_6_1/runner/r17_sync.sh > "$WORK/sync.stdout.log" 2> "$WORK/sync.stderr.log"
# 保存 rc；非零停止。
bash "$PACK/tools/run_targeted.sh" "$WORK/targeted"
```

`run_targeted.sh` 自行捕获 monitored entry 与 JUnit 检查的返回码，保存源 before/after 与测试文件 SHA。必须同时查看 monitored run_record 的 business rc 和 required/native 原件，不能仅凭脚本最后一行。

新定向预计 157 个 case（原152+5），其中 pipeline 预计47，最终以实体/collection为准。原两个 V10 case、健康实包 case 和四个拒绝 case 都必须真实执行。只对 TEST/Fixture 变更负责，不新增生成/实验权限。

## 3. 新候选 C

定向全绿、历史字节保护复核通过后：

```bash
cd "$REPO"
git add stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py
git diff --cached --name-only
git commit -m "R17 admission v3a: reuse healthy claim fixture for pipeline V10"
CANDIDATE=$(git rev-parse HEAD)
printf '%s\n' "$CANDIDATE" > "$WORK/CANDIDATE_COMMIT.txt"
git push origin route-c-stage2-6-1-repair17
bash stage2_6_1/runner/r17_sync.sh
```

只 stage 上述一个文件。已有 v3/** -text 覆盖新子目录，不需要改 .gitattributes。不要 stage WORK 或活动遥测。重新核对部署/source guard 与代码/测试/配置 clean。

## 4. 首次完整回归与真实包副本负例

此处沿用原 v3 给定脚本，字节未改：

```bash
bash "$PACK/tools/run_bound_regression.sh" "$CANDIDATE" "$WORK/full_regression"
# 保存脚本返回码；只有 rc=0 才进入副本负例。
source "$DEPLOY/activate-freqtrade.sh"
cd "$DEPLOY"
set +e
python "$PACK/tools/probe_evidence.py" \
  --runner "$DEPLOY/stage2_6_1_runner" \
  --package "$WORK/full_regression/healthy_package" \
  --out "$WORK/negative_cases" \
  > "$WORK/negative_cases.stdout.json" 2> "$WORK/negative_cases.stderr.log"
RC=$?
set -e
printf '%s\n' "$RC" > "$WORK/negative_cases.rc"
test "$RC" -eq 0
```

full regression、collect package、full verify 的原始命令/输出/rc 均保留。不得拿旧 v3 定向结果或旧 2030/7 完整回归冒充新候选结果。不要对新主实验运行 prepare/run/claim。

## 5. 新证据子目录 E

```bash
AR="$REPO/stage2_6_1/artifacts/repair17/development/v2_c13_admission_boundary_closure_v3/continuation_v3a"
test ! -e "$AR"
# 先完成保护对象前后对拍与 REPORT，再复制 WORK 内本轮原件到 AR。
# full_regression/healthy_package 必须保持原字节与目录内引用。
mkdir -p "$AR"
cp -a "$WORK"/. "$AR"/
```

根据实际结果生成 AR 内 `REPORT.md`（写明该轮结果，不更新旧 v3 REPORT）。SHA256SUMS 只覆盖新子目录自身，排除清单自身；不能重签旧 v3 根的 SHA256SUMS。

```bash
cd "$AR"
find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS
cd "$REPO"
git diff --exit-code "$CANDIDATE" -- stage2_6_1/runner stage2_6_1/src stage2_6_1/tests
# 上一条必须为空。所有旧 artifact/claim 仍按基线字节快照对拍。
git add stage2_6_1/artifacts/repair17/development/v2_c13_admission_boundary_closure_v3/continuation_v3a
git diff --cached --name-only
git commit -m "R17 admission v3a: archive continuation verification evidence"
git push origin route-c-stage2-6-1-repair17
EVIDENCE=$(git rev-parse HEAD)
```

E 只含新子树、无源码/测试/历史文件变化。不要把本次失败基线 `1ea193c…` 的 REPORT 写成 PASS。

## 6. 提交后 full 冷验（不是再次 pytest）

```bash
source "$DEPLOY/activate-freqtrade.sh"
cd "$DEPLOY"
set +e
python "$DEPLOY/stage2_6_1_runner/r17_v2_c13_regression_evidence.py" verify \
  --package "$AR/full_regression/healthy_package" \
  > "$WORK/verify_after_E.json" 2> "$WORK/verify_after_E.stderr.log"
RC=$?
set -e
printf '%s\n' "$RC" > "$WORK/verify_after_E.rc"
test "$RC" -eq 0
```

要求 ok=true、validation_scope=full。无生产 authority 的 admission_eligible=false 正常，不能为改变该值写生产根。

可将 after-E 三份原件复制到 AR 的新 `post_E_verify/`，更新该新子树自身的 SHA256SUMS，并普通 evidence-only E2/push。最终再一次仓库外 full 冷验并报告 SHA/rc，不为自指最新HEAD无穷提交。

## 7. 失败处理

任何阶段失败立即保留真实输出和阶段。不得跳过 v10、把它改为 expected failure、放宽 synthetic/production 校验、填入假摘要或再起新实现。可审查的失败实现/新证据按实际普通提交推送，明确 NOT_ADMITTED。生产 claim、历史数据不变；不执行新实验/训练。
