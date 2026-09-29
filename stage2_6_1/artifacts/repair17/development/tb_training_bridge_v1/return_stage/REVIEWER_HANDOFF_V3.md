# REVIEWER_HANDOFF_V3 — TBv1 R1/R2/R3 返修复验

你是独立 reviewer(配置模型 zhipu-coding-plan/glm-5.3-flash,未参与实现)。
复验对象:C6 = 529bb03c63378ea0e6430101b06a9bfe3d9abac8(分支 route-c-stage2-6-1-repair17,基线 5ac420a1)。

## 必读输入(按序)
1. 用户原始任务包与轮次目标(工程纵向切片;零生成/零 fit/零新增 smoke;配额不重置)
2. ChatGPT 终审 `return_stage/incoming_review/finalreview_2575deb2/REVIEW.md`(R1/R2/R3 定义与完成条件、probes/RESULT.json 6 漏检)
3. 上轮 `return_stage/REVIEWER_CONTENT_REPORT_V2.md`(你的历史结论,C3-C5)
4. `return_stage/B_FIXES.md` §R1/R2/R3、`SUMMARY.md` §1a/§C6
5. 候选源码 `return_stage/candidate_source/`(13 文件 @ C6)与 `native_probe_r1r2/`(before/after 原件)

## 复验范围(全部必需项,不只主 Agent 新增测试)
- **R1**:空 recorded+有效/非法 commit、缺任一必需键子集、错字节 => False;合法 C2 完整身份 => True(必需集合必须来自候选归档源码合同,非 manifest 自列);冷读层清空 code_identity_consumer 必须在 PPO.load 前拒(自写探针,勿只复用我的)。
- **R2**:fit_namespace 改名/episode_hash 虚构且外层摘要自洽 => 装载拒;正例(未改)装载通过;隔离(N01 旧反例)不回退。零生成零 fit。
- **R3**:包内 v1-v6 回归原件齐备且 v5/v6 与 git@2575deb2/529bb03c 绑定一致(此包封好后冷读阶段再验字节;本轮先验仓库记录绑定)。
- 全矩阵对账:22 项 + ChatGPT 16 反例 + 八类最低反例在 C6 上仍成立(未受 R1/R2 改动影响项可复用上轮证据,但须核 C6 diff 范围确实未触及)。
- 262 套件 228 passed;261 v6(绑定 529bb03c)ok=true。
- 配额:账本 SHA 前后不变(零生成/零 fit/零 optimizer/零新增 smoke)。

## 硬红线
- 脚本只写 F:/trading/tmp_reviewer_tb_v1_r3/;不修改被审产物/仓库/部署树。
- 零原生生成、零 fit、零 optimizer、零模型反序列化(PPO.load 处用 sentinel)。
- 最多 1 个重型 WSL 任务(建议:262 套件只读复跑或探针,二选一;261 v6 以仓库记录+launcher 原件为准)。
- 后端模型元数据不可见时如实记录。

## 产出
F:/trading/trading/outgoing/REVIEWER_CONTENT_REPORT_V3.md:逐项 PASS/FAIL/BLOCKED + 直接证据 + 配额声明。
