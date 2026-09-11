# 覆盖索引：验收矩阵 → 证据映射

A/F/P/C/R 编号对应 ACCEPTANCE_MATRIX.md；证据相对本归档根。

| ID | 证据 |
|---|---|
| A01 | handover/（HEAD/parent/branch/remote ref/log/status/python_env/deploy_import_identity/claim_state_readonly）+ protected_snapshots/baseline_protected.manifest |
| A02 | targeted_tests/attempt3/test_curriculum261_r17_v2_c13_claim_protocol.junit.xml::test_a02_production_authority_immutable |
| A03 | 同上 ::test_a03_no_authority_injection_surface（set_test_authority/可变全局已废除） |
| A04 | 同上 ::test_a04_combination_rejected_before_writes（RealBackend×合成、生产×fixture 双向拒绝） |
| A05 | 同上 ::test_a05_cli_and_paths_have_no_root_override（CLI 无 root 参数；域外根 fail closed） |
| A06/A07 | 同上 ::test_a06_a07_fixed_paths_and_claim_api（签名级+行为级：零 caller path/receipt） |
| A08 | 同上 ::test_a08_claim_binds_closure_and_regression_digest |
| A09 | 同上 ::test_g08_concurrent_claim_exactly_one_wins（两进程恰一胜）+ ::test_g07_second_checkout_cannot_reacquire |
| A10 | 同上 ::test_g10_claim_survives_crash_no_recovery（含损坏 claim fail closed、无恢复接口断言） |
| F01 | claim_protocol::test_g11（unspecified/自报 rc 形状拒绝）+ synthetic_chain::test_e01（无包 preclaim 拒绝）+ negative_cases/01、02 |
| F02 | regression_evidence 单元::test_negative_symlink_to_healthy_package、::test_negative_dotdot_escape_rejected、::test_negative_non_regular_file + negative_cases/15、16 |
| F03 | regression_evidence::test_healthy_control…（18 必需文件/命令身份层）+ negative_cases/19 |
| F04 | ::test_healthy_control（junit 2037/0/0、计数一致）+ negative_cases/03、04、05 |
| F05 | ::test_negative_critical_test_skipped、::test_negative_unlisted_skip…（逐 id allowlist）+ full_regression/20260911T205757Z 包 skips_allowlist.json（7 id、无新增证明） |
| F06 | regression_evidence::test_full_mode_candidate_commit_missing / ::test_full_mode_candidate_drift / ::test_full_mode_worktree_dirty + negative_cases/13、14 |
| F07 | ::test_full_mode_healthy… / ::test_full_mode_lock_vs_deploy_import_differ + healthy_package/source_closure.json + zero_production_side_effects |
| F08 | E 提交前检查（commit_e.sh 输出：C3..E runner/src/tests diff 为空）|
| F09 | negative_cases/09、10、18、19 + regression_evidence::test_negative_stdout_appended、::test_negative_required_file_bytes_changed |
| F10 | regression_evidence::test_negative_tamper_with_manifest_resign…、::test_negative_package_digest_changes_on_manifest_resign + synthetic_chain::test_e11_regression_digest_anchor_rejects_resign_only |
| F11 | synthetic_chain::test_e11_regression_tamper_rejected_before_claim（claim 前拒绝、零生成） |
| F12 | regression_evidence::test_healthy_control_passes_structural_and_is_read_only（前后 tree snapshot 相同）+ negative_cases 各 case after.sha256=before |
| P01 | targeted_tests/attempt3/test_curriculum261_r17_v2_c13_source_provenance.junit.xml::test_p01（字节= c9152b62…，blob=3376fca 于 handover 与 commit_c 记录） |
| P02 | 同上 ::test_p02（成员集/角色声明/无自指） |
| P03 | 同上 ::test_p03（source_guard 用治理 lock + 篡改探测 + 历史 lock 字节不变） |
| P04 | 同上 ::test_p04_p05（591b1f35… 不可用、归档 plan 见证存在）+ source_provenance/source_provenance.json |
| P05 | source_provenance/source_provenance.json（五闭包角色/可用性分层） |
| P06 | protected_snapshots/diff_summary.json（3442 文件零变化；遥测区单列） |
| C01/C02 | targeted_tests/attempt3/test_curriculum261_r17_c2_launch_prep.junit.xml::test_c01 / ::test_c02 |
| C03-C08 | 同上 ::test_c03_real_selector_behavior_differential（10 场景对真实 mechanical_selection）+ c2_selector_behavior/c2_prep_report.json |
| C09 | 同上 ::test_c06_c09_zero_call_sentinels_all_zero（十入口计数 0）+ zero_production_side_effects/c2_prep_report.json |
| R01 | targeted_tests/attempt3/*（117/0/0/0，六文件零 skip）+ official（124/0/0，C 字节）+ reader_binding 于全量回归 7/7 |
| R02 | synthetic_chain::test_e01（合成链完整协议）+ regression_evidence::test_production_verifier_rejects_synthetic_domain |
| R03 | full_regression/20260911T205757Z（entry rc 0；2030 passed/7 skipped；junit/run_record/summary/telemetry/native 全 present） |
| R04 | healthy_package（required 角色逐字节 + supervisor 双锚校验绿 verify_healthy.json） |
| R05 | commit_e.sh 输出（C3..E diff 空 + final_import_identity.json == 治理 lock） |
| R06 | zero_production_side_effects/（claim 字节不变、C2 哨兵 0、生产根零写入） |
| R07 | SHA256SUMS 自检 + 本根为全新目录（旧 artifact 未触碰） |
| R08 | git 历史：C=706614f、C2=2ef1b29、C3=19bd26f、E=<见首页>，均普通提交已 push（远端 ref 见 handover 与报告） |
| R09 | FINAL_REPORT.md 首页（工程治理/C2 prep/统计 NOT_RUN/formal NOT_ISSUED 分列） |
