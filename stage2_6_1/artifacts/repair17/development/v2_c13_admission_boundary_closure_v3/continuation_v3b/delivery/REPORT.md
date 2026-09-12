# R17 v3b 轮次报告（Test Source Map / Safe Evidence Export）

任务：R17V2C13TestSourceMapAndEvidenceExportClosure-v3b
仓库/分支：ceyirelehe47/freqai-rl-platform-audit / route-c-stage2-6-1-repair17
基线（接手 HEAD）：71a815c676e484ff5b97dbd230a40923ff468ae5
代码候选 C：4bdfe5dc24d21461c2b46614aff8c0e6c0144cd3
E（证据提交）：待 S6 本地提交后填写于 post_E；本报告结论 PENDING_POST_COMMIT_VERIFY。

## 结论（导出前状态）

- 本轮测试映射/归档工程：PENDING_POST_COMMIT_VERIFY（等待 E 提交后真实 full 冷验与 E2，不提前 PASS）。
- 本轮新业务统计：NOT_RUN。正式资格：NOT_ISSUED。C2 namespace / 新训练：NOT_STARTED。
- 旧 v3/v3a 失败不追认；旧 C→E 链在旧规则下仍判失败；所有失败 attempt 原件永久保留。

## 31 个根目录测试误判的更正

上轮（v3a）将部署测试目录中 31 个 r4–r8 测试文件判为"未跟踪陈旧文件"并隔离。本轮以候选 Git 对象核实：
它们是候选 stage2_6_1/tests/ 根目录的合法受跟踪测试（r4×5、r5×7、r6×6、r7×6、r8×7），经 r17_sync.sh
递归 basename 平铺 + 全 CR 字节删除进入部署。旧 reader 错误地把部署路径拼回嵌套目录导致 31 项
test_file_hash_mismatch；第二轮 1832 case 是移除这 238 case 后的子集，不构成完整回归。本轮新 guard
以 candidate_test_map() 从 Git 源树反推完整映射并四方绑定（部署/manifest/collection/JUnit），
31 文件已恢复并在完整回归中执行。旧隔离目录与旧报告只读保留，本报告单独更正，不改旧件。

## 实际执行计数

- 本包快速检查：57 case，0 fail/error/skip（pack_checks/junit.xml，rc=0；非项目全量回归）。
- 八文件定向：178 case（157 基线 + 21 个 v3b 映射 case），0 fail/error/skip/xfail；V10 核心与健康
  case 全部实际执行（junit_check.ok=true，v3b_mapping_cases=21）。
- 候选 C 完整 R17-first 回归（同候选一次）：129 个测试文件全部执行；总计 2091 case = 2084 passed +
  7 skipped（与源码固定 HISTORICAL_SKIP_IDS 七项逐一相符；本轮 critical 文件零 skip）；其中 31 个
  根目录来源文件贡献 238 case。原 collector（collect）与实际 full verifier（verify_C）均通过：
  ok=true / validation_scope=full / admission_eligible=false（无 authority 的审核 CLI，语义正确）/
  guard_version=R17AdmissionBoundary-v3b / errors=0；package_sha256=eb4e4163ce3eed4a02f112dbfb6d265ae1d954e47ab016acdbc1ad133350cabe。
  pytest 原始摘要行：2084 passed, 7 skipped, 9 warnings in 2179.83s (0:36:19)
- 映射诊断：python 文件 130（129 test + 1 conftest），根目录来源测试 31；同名/大小写折叠冲突零；
  source_before==source_after、test_mapping_before==test_mapping_after。

## 负例与健康控制

- 健康包 full 验证通过；10 类隔离副本负例全部于预期错误层拒绝（required/critical/JUnit/collection/
  import/supervision/symlink/新 test_candidate_set_mismatch/新 test_manifest_duplicate）；
  原健康包前后字节不变。
- 真实 symlink 负例（nested_directory_symlink）实际创建链接并被真实 reader 拒绝；
  导出阶段该链接以普通 _LINK_RECORDS/*.json 惰性记录（readlink 原始字节 + 类型/路径/size/SHA），
  不再作为 Git blob 入库；生产 reader 不放宽 120000。

## 保护与环境记录

- 历史锁 c9152b62192a93571c16ba62e0ef2e70522f108726f3eb83fd25d48007a77c55 全程未变；
  旧保护区快照 protected_before(5320 项) 与轮末对拍 unchanged=true（含 v3a 2 个历史 symlink 原样）。
- run_supervision 活动追加单独记录（handover/run_supervision_status.txt），未清理、未入提交。
- 环境治理（均留证于 handover/）：部署测试面内陈旧 .pytest_cache（裸 nodeid，证明来自历史以
  tests 目录为 rootdir 的旧调用；官方脚本 rootdir=$DEPLOY、cache 写部署根不在守卫面内）已移除，
  清单见 pytest_cache_removal.txt；pack_checks_attempt1_rc127 为激活脚本缺失导致的首次失败残迹。
- 网络操作（git fetch/ls-remote/push）在 Windows 宿主侧执行（WSL git 网络不可用），见
  handover/network_note.txt；其余全部步骤在 WSL 实机执行。
- S1 预映像恢复目录按 RUNBOOK 布局移入 WORK/recovery（原创建于 /home/cryptorl/projects/crypto_rl/work/r17_v3b_20260912T052941Z/recovery，同在发布库外）。
