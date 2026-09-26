# D:新 reader 对原研究只读复验记录

时间:2026-09-26T17:47–17:48Z(全量回归并行期间执行;只读,无生成)。

## 身份三方(单件制品内可区分)

| 角色 | 身份 | 来源 |
|---|---|---|
| 数据/计划(creator 声明) | entry_sha256 = 6aa45601138f4a76… | 旧 plan/manifest 声明;原件未找回(C1) |
| reader(实测) | 4e983cecbd3e145a… | 候选 48939c0 的部署入口字节,读取时实测 |
| 分析入口(实测) | 79990fcf9492ce72… | r20_design_calc_v4.py,reader 读取时实测 |

结果 JSON:`reader`(实测身份+note"不倒填")、`plan_declared_creator`
(声明身份)、`historical_execution_provenance.status=not_established`
(manifest 为 v1,仅 creator 声明;数值复算不受影响,不以来源不足冒充
数据损坏,亦不把数值复算包装成历史生成过程验证)。

## 执行

```
python <deploy>/stage2_6_1_runner/r25_cue_bias_dev_entry.py cold-read \
  --plan <repo>/…/r25_cue_bias_dev/plan/dev_plan.json \
  --out-root <repo>/…/r25_cue_bias_dev/study \
  --result <work>/d_reader_recompute/cold_read_result_v2.json
```

- 输入前/后 `plan study` 全 79 文件 SHA-256 清单逐字节一致
  (`inputs_before.sha256` / `inputs_after.sha256`,diff 为空)。
- reader 不调用生成/fit/训练;bootstrap 为既有事件复算
  (20,000 次/seed 20270102,与封存原件同函数)。

## 结果(integrity=valid,complete_k=true,problems=[])

- 11/11 坐标 recall 与 bootstrap SE 与最新独立复核参照值全部一致
  (差 < 5e-10;逐坐标值见 result JSON,验证脚本输出在
  `per_coordinate_check.txt`)。
- 主聚合逐位复现:delta_bar = 0.00006146679677406079;
  S_raw = 0.0005675046775357165;S_analysis = 0.0008512570163035747;
  CI90 = [-0.001338726393960762, 0.0014616599875088836];
  magnitude=within_equivalence_bounds;direction=not_resolved;
  contrast_r1 同判。
- 语义:本结果为**新 reader 对旧事件的条件数值复算**(primary 带
  interpretation 标注),历史执行来源未证明的限制保留。
- 事件计数对拍:validation 合计 142,597(检出 135,520)、model 合计
  142,628,总 285,225 —— 与独立复核一致(由 rows n_events 累计)。

## 旧件不动声明

旧 plan/study/smoke/回归/监护原件零字节改动(哈希清单为证);
`study/cold_read_result.json`(旧 reader 历史输出)保持原样,新结果
只写在本 work 目录。
