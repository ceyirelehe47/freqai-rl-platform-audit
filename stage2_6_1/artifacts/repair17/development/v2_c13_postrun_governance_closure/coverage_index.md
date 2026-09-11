# Coverage Index — R17V2C13PostRunGovernanceAndC2LaunchPrep-v1

每项验收绑定真实测试名与证据原件。测试运行环境：WSL
CryptoRL-Ubuntu-24.04 / cryptorl / freqtrade-rl / 部署树
~/projects/crypto_rl（r17_sync 同步自发布库）。

## G 组（协议）

| ID | 测试/证据 |
|---|---|
| G01 | handover/t0_identity.txt（HEAD/parent/branch/python/vendor/import SHA）；远端 ref fetch 核对（无前进） |
| G02 | original_byte_snapshots/snapshot_before.tsv（5968 文件）+ snapshot_after.tsv + snapshot_diff_report.txt |
| G03 | test_curriculum261_r17_v2_c13_claim_protocol.py::test_g03_plan_persist_create_only_fsync_readback / ::test_g03_plan_digest_self_consistent |
| G04 | ::test_g04_claim_requires_persisted_plan_file / ::test_g04_claim_rejects_in_memory_plan_drift |
| G05 | profile.write_preclaim_receipt/validate_preclaim_receipt_shape + test_g11_receipt_shape_and_stale_closure_rejected |
| G06 | ::test_g06_no_env_root_override_in_production_module |
| G07 | ::test_g07_claim_root_escape_rejected / ::test_g07_second_checkout_cannot_reacquire |
| G08 | ::test_g08_concurrent_claim_exactly_one_wins（两进程 O_EXCL） |
| G09 | ::test_g09_plan_tamper_before_claim_rejected（等长篡改） |
| G10 | ::test_g10_claim_survives_crash_no_recovery |
| G11 | ::test_g11_receipt_shape_and_stale_closure_rejected / ::test_g11_missing_receipt_fails_closed + reader_binding::test_run_requires_authoritative_plan_first / ::test_run_rejects_stale_receipt_or_evidence_drift |
| G12 | ::test_g12_plan_identity_stable_across_planning_only_hits / ::test_g12_admission_evidence_reference_validated + synthetic_chain 全链（prepare→run 消费同一 plan） |

## P 组（双闭包）

| ID | 证据 |
|---|---|
| P01 | source_provenance/provenance_dual_closure.json（三闭包分层） |
| P02 | source_provenance/search_log.txt（全盘搜索）+ matches.txt 空 + execution_source_bytes_available=false |
| P03 | 同 P01 的 post_run_reader_v2round 节（93f2d59a 仅事后 reader） |
| P04 | 同 P01 的 governance_fix_this_round + rule_p04（未来 plan/claim/run record 绑定执行闭包） |

## E 组（冷读绑定）

| ID | 测试/证据 |
|---|---|
| E01 | verify episode_artifacts 键集精确（pipeline.py verify;synthetic_chain 健康链走查） |
| E02 | synthetic_chain::test_e02_selected_episode_inputs_reload_and_hash（生产 _reload_episode_identity 全量对拍，≥48 episode） |
| E03 | 同 E02（CSV sha 与 episode hash 分层断言）+ reader_binding::test_e03_multiset_hash_stdlib_matches_production |
| E04 | verify fit manifest 逐成员 + test_e03_multiset_hash_stdlib_matches_production（差分）+ synthetic_chain E04 负例 |
| E05 | verify eval 逐成员链（合成链+旧归档控制组） |
| E06 | verify conditions 派生核对 + synthetic_chain::test_e04 负例1 + reader_binding E10 stat_flip |
| E07 | verify canonical 成员精确 + reader_binding E10 canonical 负例 |
| E08 | reader_binding::test_e08_routing_audit_flags_unbound / ::test_e08_require_eval_routing_passes_bundle_hash + verify routing 交叉段 + E10 routing 负例 |
| E09 | 既有 test_b03/b04（实际对象/inner 漂移）保留通过；routing bundle 取用核对 |
| E10 | reader_binding::test_e10_archived_copy_semantic_negatives（五负例+控制组，对现存 v2 只读副本） |

## S 组（历史结论）

| ID | 证据 |
|---|---|
| S01 | reader_binding::test_s02_archived_v2_four_state_verdict（stored 四格 True 只读；κ/样本未动） |
| S02 | 同上四态断言 + independent_verdict/verify_stdout.json（CLI rc=1） |

## C 组（C2 准备）

| ID | 测试/证据 |
|---|---|
| C01 | test_curriculum261_r17_c2_launch_prep.py::test_c01_candidate_set_exactly_three |
| C02 | ::test_c02_n_options_and_mechanical_order |
| C03 | ::test_c03_binding_sources_dedicated_only |
| C04 | ::test_c04_r16_fail_and_control_not_selection |
| C05 | ::test_c05_no_namespace_claim_or_plan_registered + c2_calibration_launch_preparation/（报告/草案/JSON） |
| C06 | ::test_c06_zero_generation_calls（哨兵） |

## R 组（回归与交付）

| ID | 证据 |
|---|---|
| R01 | 定向 57+54 passed（claim_protocol_tests/ reader_positive_negative/ stdout 原件）；全量 full_regression/ |
| R02 | 同上 junit.xml/stdout.log/run_meta.txt（ENTRY_RC/命令/env） |
| R03 | original_byte_snapshots/ 前后对拍 + SHA256SUMS（交付清单） |
| R04 | git log（普通 commit + push origin route-c-stage2-6-1-repair17；无 amend/force） |

## 零生成声明

全轮生产 generator 调用、fit、eval、canonical、policy、claim、
exposure 计数 = 0。合成链产物全部位于 pytest tmp（synthetic 标记，
不入归档、不被 production verifier 接受）。
