# R17 v3b E 后冷验最终报告

E（证据提交）：00630a67565beda3787739c2b67642f1b3d9478d；候选 C：4bdfe5dc24d21461c2b46614aff8c0e6c0144cd3；本报告由 post_E 新增原件承载，delivery 一次封存不改。

## 三层结论

1. 本轮测试映射/归档工程：E 提交后真实 full 冷验通过（rc=0，ok=true，scope=full，
   admission_eligible=false 为无 authority 审核 CLI 的正确语义），E..HEAD 待 E2 后由外部终验。
2. 本轮新业务统计：NOT_RUN；正式资格：NOT_ISSUED；C2/新训练：NOT_STARTED。
3. 旧 v3/v3a 失败与旧 C→E 链不追认；旧规则对历史 120000 的拒绝不变。

## 导出与暂存摘要

- export：389 普通文件逐字节复制 + 1 个授权负例链接以 _LINK_RECORDS/*.json 惰性记录
  （readlink 原始字节 base64/size/SHA，未跟随、未重现）；源 WORK 未变。
- 导出对拍 verify：ok，导出树无任何活链接/特殊对象。
- 暂存门禁 staged：390 成员全部 100644 普通 blob，工作树与 index 集合一致，无 .gitignore 漏收。
- 完整回归证据（delivery/full_regression）：2091 case = 2084 passed + 7 skipped（历史白名单），
  129 文件全执行，含 31 个根目录来源（238 case）；verify_C 与 E 冷验的 package_sha256 一致性
  见 result.json 与 delivery 内原件。
