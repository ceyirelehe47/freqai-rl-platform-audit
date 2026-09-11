# 勘误（E3,验收观察项整改;evidence-only）

1. protected_snapshots/diff_summary.json 与 after_protected.manifest 在 E=da3e606
   中遗漏未拷贝(生成于部署侧 work 目录);本勘误补交。内容与 FINAL_REPORT §3
   引用的数字一致(3442 文件零变化;遥测 base 4914 → after 4998,+84)。
2. zero_production_side_effects/ 目录(claim_zero_write.json 等)在 E 中遗漏;
   本勘误补交。claim 两个 json 与 handover/claim_state_readonly.txt 接手快照
   逐字节一致(93f5181f…/09f2227d…)。
3. full_regression/skips_allowlist_final.json provenance 文字笔误:"candidate C2"
   应为 "candidate C3 (19bd26f)"。文件其余内容(junit 提取的 7 个 id 与
   无新增 skip 证明)不受影响;保留原字节不改动,以本勘误为准。
4. regression_evidence_verifier/negative_cases/ 补交 layer_precision.json 的
   生成脚本 check_layers.sh;观察项"case 11 期望层非首层"如实说明:该变异
   同时触发计数层(collected_count_mismatch)与 required 锚层
   (required_file_mismatch),期望层在 errors 第三位命中,未到达首层是
   变异副作用,不是层缺失。
