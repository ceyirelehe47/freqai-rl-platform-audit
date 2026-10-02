# SUMMARY — RouteC_FormalLaunch_Preparation_v1

## 判定(区分三件事)

1. **正式启动适配已实现并在隔离边界验证**:受信任部署配置
   formal_ready 读取/校验面(环境重定向拒、零 mkdir 根解析)、
   批准原件(qfap-)→formal admission authority 签发→正式许可
   (计划/批准双绑定)→一次性消费链;A 复用权威 17 步与真实
   业务入口(chain-run/_chain-bounded,显式部署绑定新正式根,
   旧 R17/R19 状态零写);B 11 坐标正式清单传入现有坐标锁与
   审计核心(formal=True,500/1e6);只读预检(重复执行内容
   身份稳定)。42 项新隔离测试 + 相邻 qprod 248 项 + 262 全套
   240 项全绿;r21 全收集回归见 evidence/regress261(本包)。
2. **待批计划已准备**:DECISION_FOR_APPROVAL.md(A1 停 qualify/
   A2 完整链含 256 步 smoke 二选一 + B 独立批准;固定锚 P0
   条件口径;全部额度与停止/失败语义;明确不执行事项)。
3. **真实正式运行未授权/未运行**:生产部署无 formal_ready 配置、
   无批准原件、无正式许可、无 admission;真实 Level A/Level B/
   教学 NOT_RUN。本轮业务消耗=0(生成/MC/fit/optimizer/模型
   加载均为 0;保护根前后快照零漂移)。

## 候选与验收链

- 基线 73371e1e(QProd C25 CLOSED PASS 封包 HEAD)→ 候选
  df6e7eab → 修复提交 **e1f23d7e**(最终候选)。
- 独立 reviewer(OMP task 工具 reviewer 角色;用户指定 dsv4.1f,
  配置解析=commandcode/deepseek/deepseek-v4.1-flash;运行环境
  未回传后端元数据,模型归属不代签):第一关 R1 FAIL 1 项
  (curriculum261_api.py 新哈希未在 ppo262_input_lock 登记,
  2 个 262 守卫测试失败)→ 修复(双树同步登记)→ R2 复验
  **第一关 PASS**(独立复算哈希/三处副本一致、三项复验条件、
  240/240、C1-C7 全 true)。原文:F:/trading/local/
  reviewer_flp_v1_gate1.md、reviewer_flp_v1_gate1_r2.md、
  F:/trading/local/reviewer_flp_v1/(probe 脚本+输出)。
- 第二关(完整 F01-F12 矩阵 + 最终 ZIP 字节冷读)见
  REVIEWER_FINAL_RECEIPT.md(包外)。

## 变更面

src:curriculum261_api.py(休眠正式 namespace 22 名)、
curriculum261_qprod_permit.py(issuer kinds+profile 绑定)、
curriculum261_qprod_plan.py(audit_budgets 按 profile 分支)、
curriculum261_qprod_coordinate.py(白名单按 profile+身份集+
formal)、curriculum261_qprod_formal.py(新)、
curriculum261_qprod_formal_levela.py(新)、
ppo262_input_lock.py(登记表,两树同步)。
runner:qprod_formal_authority.py、qprod_formal_level_a_entry.py、
qprod_formal_level_b_entry.py、qprod_flp_r21_regress.sh(新)。
tests:test_curriculum261_qprod_formal_launch.py(新,42 项)。
report:readiness 页修订注记。
准备包:artifacts/repair17/development/formal_launch_prep_v1/
(DECISION_FOR_APPROVAL/TECHNICAL_APPENDIX/drafts/evidence/
sandbox/scripts)。

## 已知非阻断观察(reviewer 第一关)

1. B 原生预算记账在成功返回后(中断路径已有中断标记+一次性
   许可兜底,不构成越额);
2. validate_formal_permit 未逐项对拍 quota/stop(经计划 digest
   间接绑定,当前无可达利用路径);
3. 已在 DECISION 文档点明 A1 预算表 vs 授权面口径差异。

## 环境事实

正式耗时无当前实测(标未知);工作区变更按任务书边界零越权;
QProd 原生 2/2 与 TrainingBridge 旧账未动。
