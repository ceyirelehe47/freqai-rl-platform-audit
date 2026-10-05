# RCF R2 独立复验(dsv4.1f)— 证据目录 /f/trading/local/rcf_r2_review/

被审候选 commit = eca28ea1edddf5229dfc3dc54bcf3510428c3fca
(parent 97f81a6d0619af3a96aaf9fca7dc33e2cc720d24),6 文件:2 文档 + 3 代码 + 1 测试。
复核部署树两处(crypto_rl_qaf_v2 / crypto_rl_formal_a_qaf_v2)4 个关键文件 sha256
与候选 git blob 逐一相等(642024c99/0fb46d4c/d59c2172/3adc4093)。
真实 deploy /home/cryptorl/projects/crypto_rl 未触碰(.r17_formal_admission.json
与 r17_admission_issued.jsonl mtime 仍为 2026-09-20)。
本目录内所有签发/链执行均为隔离沙箱(deploy-authority-admission 全在
/mnt/f/trading/local/rcf_r2_review/ 下),与生产零签发分开陈述。

## 探针与结果(全部独立构造;不重跑作者测试作为唯一判据)

P1 p1_guard_links.py(候选 vs parent 97f81a6d 对照;14/14)
- a1 两悬空文件链接→拒;保护域零创建;art 仅两条链接
- a2 链接→已存在错误字节文件→拒(异物);目标字节不变
- a3 链接→已存在正确字节(json 单件)→拒(半写);零写
- a3b 两链接→已存在正确字节→幂等接受,零经链接写入(观测量)
- a4 合法新目录安装+幂等(mtime 不变)对
- a5 报告链接→历史原件:候选拒(写时 O_NOFOLLOW ELOOP),原件不变;
      parent 对照:原件被覆盖(反例复现→修复有效)
- a5b 报告悬空链接:候选入口拒且不创建目标;parent 对照经链接创建目标
- a5c 合法报告路径正常写出
- a6 【缺陷】同路径长报告(2215B)→短报告(669B)覆盖:
      候选文件仍 2215B=新JSON+1546B 陈旧尾部,json.loads 失败;
      parent 对照 670B 精确等于短报告、可解析
- a7 混合目录 allow_replace_broken 拒(既有行为);a7b 链接→错误目标
      allow_replace:替换的是链接本身,目标字节不变

P1b p1b_cli.py(CLI 面;3/3)
- c1 operator prepare + 悬空链接→rc≠0,保护域零创建
- c2 operator prepare 合法目录→rc0 真装
- c3 guard preissue --report-out 链接→rc3 受控拒绝,历史原件不变

P2 p2_operator.py(operator 级;8/8)
- s1a/s1b 真实字段(runs[0].cwd)错 cwd→深核 reason=
      regression_collection_run_cwd_not_deploy_root;operator rc96、
      authority/admission/签发日志/permit 零新增(快照相等)
- s1c 【缺陷】作者式改法(块级 cwd 键 + record 移到 base/):reason=
      regression_junit_missing:junit.xml —— 拒绝来自记录搬迁后相对原件
      解析失败,与 cwd 无关 → 该测试不能证明 cwd 核验
- s2 junit 缺失→拒; s3 junit 篡改(sha 失配)→拒; s4 deploy src 漂移→拒
      (reason=regression_import_surface_deploy_mismatch),三者均 rc96 零一次性写
- s5 全链正常路径:permit==1、admission 文件+签发日志各 1、marker v2
      (prerequisites_executed 双 true、stress_namespace=stress_qaf_v2、
      science_executed=false)、chain_budget_gate.consumed[determinism-matrix]
      非空(根 gate 命中)、determinism/ 无产物、步1 verify pass=true、
      chain failed_step=audit、rc=1(链诚实失败于下一前置)

P4 p4_gate.py(RCF-03 生产等价/相邻反例;7/7)
- g1 工程路径无 gate 无 env:rc0+marker v2+无 gate 创建,行为同 parent
- g2 根 gate 命中+consumed; g3 子目录布局 fallback 命中+consumed
- g4 gate 计划不含该步→rc2 无 marker; g5 缺 gate+正式 env→rc2 fail closed
- g6 已消费→rc2 无 marker; g7 非法 attempt→argparse rc2 无 marker

作者套件复跑(部署树同源):closure 26 passed(98s);
guard+launch 67 passed(39s) — 与其声称数字一致。

## 发现

F1(P2)preissue --report-out 覆盖未截断(stale 尾部):
  curriculum261_qaf_provenance_guard.py:222-224,
  _open_no_follow 非 exclusive 缺 O_TRUNC。最小复现:a6。
F2(P2)test_wrong_cwd_record_refused_pre_permit 未触及 cwd 核验:
  test_curriculum261_qaf_v2_reviewclosure.py:1049-1053。
  最小复现:s1c(reason=junit_missing);正确改法见 s1a/s1b。

---

## R2 修复轮复验(候选 d705c494b031823570a90deeed891bcbe763d1d9,parent eca28ea1)

修复 diff(2 文件):guard `_open_no_follow` 非 exclusive 分支 `flags |= os.O_TRUNC`;
wrong-cwd 测试改真实 `runs[0].cwd`/`execution.runs[*].cwd`、记录留原目录、用后
清理、加 `assert "cwd" in proc.stdout` 绑定 cwd 专属拒绝理由。
部署树核验:crypto_rl_qaf_v2 内 guard=1a00d0c8…、reviewclosure 测试=642f9bf2…
均等于 d705c494 git blob;operator/preissue guard 面未变(d59c2172/b765c6ac)。

复验结果(全部在 d705c494 部署态重跑;日志 reverify_d705c494.log):
- P1 14/14:F1 关闭——a6 长 2215B→短 668B 覆盖后文件恰为 668B、精确截断、
  json 可解析(修复前样本留证 evidence_a6_eca28ea1_corrupt_sample.json);
  其余 RCF-01 链接/报告场景与 parent 对照不回退。
- P1B 3/3;P4 7/7(g1-g7 预算门/哨兵全绿,无回退)。
- P2 9/9(新增 s1d 复刻修复后测试形状:reason=…cwd_not_deploy_root、rc96
  零一次性写;s1c 保留展示旧形状为何不构成 cwd 证据;s2/s3/s4 拒绝不变;
  s5 全链:permit=1、marker v2、gate consumed、determinism/ 空、failed_step=audit)。
- 作者套件复跑:closure 26/26(95s);guard+launch 67/67(36s)。
- 修复前基线留档:p1_results_eca28ea1.json / p2_results_eca28ea1.json。

结论:F1/F2 已闭合,三工作面面无回退;d705c494 通过本轮独立复验
(重型全周期 部署+全收集+W4 由主 Agent 侧执行)。
