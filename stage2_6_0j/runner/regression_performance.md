# 阶段 2.6.0j 回归性能与轮次记录

环境:WSL2 CryptoRL-Ubuntu-24.04(内核 6.18.33.2)/ conda freqtrade-rl /
CPython 3.11;regression_runner 2 worker + 互斥目录(0h/0i/0j)独占。

## 开发期轮次(quick/affected 级)

| 轮次 | 范围 | 结果 | 用时 |
|---|---|---|---|
| 0i 目录适配轮 | tests/route_c_stage2_6_0i | 78 passed(适配后) | ~15:15 |
| 0j 首轮 | tests/route_c_stage2_6_0j | 59/35(body 缩进/notes 模板机制) | 17:00 |
| 0j 第二轮 | 同上 | 78/16(缩进归一化) | 23:52 |
| 0j 第三轮 | 同上 | 66/28(类体相对缩进/承诺属性) | 17:39 |
| 0j 第四轮 | 同上 | 84/10(time allowlist/ExamPack notes) | 24:24 |
| 0j 第五轮 | 同上 | 92/2(status 路径/os.write 合同) | 23:58 |
| 0j 第六轮 | 同上 | **94/94 全绿** | 22:49 |
| 0g/0h 适配轮 | 0g+0h | 43 失败 -> 8 -> **0g 149/0h 138 全绿** | 21:18+21:33 |
| 0i 适配轮 | 0i(零 import 合同顶层化) | **78/78 全绿** | 15:31 |

## full-cold 轮次

| 轮次 | totals | 用时 | 备注 |
|---|---|---|---|
| #1(20260830-012013) | 1506/50/0/0/0 | 4616s | 0g 9+0h 34+0i 7(v3 lock 构造/旧 body import) |
| #2(20260830-051023) | 1549/7/0/0/0 | 4760s | 仅 0i 7(零 import 合同冲击) |
| #3(20260830-065905) | 1555/1/0/0/0 | 4961s | 仅 random 入 allowlist 后的一条断言 |
| #4(最终) | **1556/0/0/0/0 all_green** | 见 fullcold4 | 断言适配后全绿 |

注:#3 -> #4 之间唯一的代码变化是一条纯 AST 断言适配
(test_hardware_instruction 的 purity 断言随 random/threading 进入
allowlist 更新),无运行时行为变化。

## 单目录耗时(full-cold#3 实测)

0j(94 项,密封计算攻击矩阵 + 完整私有链路)约 22-23 分钟,是最大
单项;全部 15 目录 wall 约 83 分钟。
