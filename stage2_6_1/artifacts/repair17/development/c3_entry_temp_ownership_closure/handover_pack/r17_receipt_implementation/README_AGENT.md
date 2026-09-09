# R17 回执入口与临时件所有权：已实现代码的测试交接

本包交付的是实现代码与测试，不是要求你再根据设计重写一遍。

## 1. 身份与本次分工

- 仓库：`ceyirelehe47/freqai-rl-platform-audit`
- 分支：`route-c-stage2-6-1-repair17`
- 编写时读取的 HEAD：`24eaa81cf36b1bfa8755145ba56d1996653e9d50`
- 待替换 reader Git blob：`93d0172b6428b1710ebc21900247473b5a4d3e64`
- 真实文件：`stage2_6_1/runner/r17_c3_engineering_slice.py`
- 本包没有提交或推送远端，没有运行用户 WSL、生成课程或触碰正式身份。

ChatGPT 已编写替换代码、针对性测试、版本校验应用器及实际 reader CLI 检查脚本。Agent 负责核对、应用、固定环境验收、归档和提交。发现失败先保存实际输入、输出、代码身份和退出码，回传最小反例；不要改测试预期、删用例或重新设计一份实现来取得绿色。环境路径修正可以进行，但需单独说明。

## 2. 已实现内容

`implementation/receipt_block.py` 是直接插入 reader 的完整回执辅助代码块，不是审查时转录的旧 helper，也不会新增运行时模块依赖。

**原末端条目与实际目标分开。** 严格解析原父目录，再对该父目录中的原末端名执行不跟随链接的 `lstat`。跨目录悬空链接、现存文件、目录等均拒绝；不再用目标父目录猜测原链接条目。后续只使用已准入的 confirmed 路径。

**只允许普通缺失后缀。** 首先用内核检查原始路径，避免 `file/../new` 被库归一化掩盖；再用标准库 `realpath(strict=True)` 确认现存部分。仅 ENOENT 可以逐级剥离普通新建后缀；悬空祖先、缺失后缀中的 `..`、ENOTDIR/EACCES/ELOOP 等拒绝。没有 strict=False 降级，也不要求升级 Python 或新增依赖。

**创建成功才取得临时件所有权。** `os.open(O_CREAT|O_EXCL)` 成功后立即接管 fd；包装失败关闭 fd，后续失败只清理已创建且身份匹配的临时件。创建冲突不删除既有对象。初始错误与 close/unlink 等后续错误同时保留。发布后清理失败时，尝试仅撤下本次同身份候选；撤下失败也明确保留，不输出成功。

保留首次发布 `os.link` 的不替换语义、本次候选的身份更新、参数/摘要/p52/生成/评估代码和现有 CLI 错误类型。输入保护与普通正常新文件、嵌套目录、有效父目录链接的行为有测试。

威胁范围仍是静态本机路径与可控 I/O 故障，不宣称抵御管理员持续改挂载或恶意祖先目录竞态。

## 3. 实际完成的本地验证与限制

最终本地结果：**54 个实现单元测试通过**。测试直接加载本包将被插入的代码块，使用真实临时文件、链接、独占创建及限定系统调用故障注入；覆盖路径、临时名冲突、包装/写入/flush/fsync/close/发布/清理故障，以及初始与二次错误保留。

另有 **4 个应用器机械检查通过**：唯一替换边界、无关函数保持、Git blob 算法及多文件 patch 的 git apply；使用的是合成临时 Git 仓库，不是用户完整 checkout。

运行环境是本地 Linux / Python 3.13.5。补丁应用到完整 reader、Python 3.11.16、原 slice 测试、真实数据 CLI 和 WSL 隔离冷读 **尚未执行**。`verify_reader_in_checkout.py` 已完成语法检查，待你执行。

容器通过 GitHub connector 读取了固定文件和待替换范围，但直接下载/物化完整源码失败。因此没有将片段测试称为完整 reader 集成；应用器会在你的真实 checkout 上完成完整文件身份核验、实际源代码变换、全文件编译、完整 diff 和 git apply 检查。

原始 stdout/JUnit、第一次测试断言失误及修正说明都在 `evidence/`。第一轮 52 通过、1 失败是测试错误地要求允许创建/清理临时件的外部目录 mtime 也不变；修正为核对输入、链接、目标文件和无残件，未放宽输入零改动要求。最终测试另增了库折叠前的内核 ENOTDIR 检查。

## 4. 应用方式

先将包解压到 checkout 外部的一个新目录。使用发布仓库根，而非只含部署代码的 `~/projects/crypto_rl` 作为 `--repo`。

```bash
source ~/projects/crypto_rl/activate-freqtrade.sh
python --version
# 应为业务固定环境 Python 3.11.16；不升级环境。

BUNDLE=/绝对路径/r17_receipt_implementation
REPO=/mnt/f/trading/freqai-rl-audit

python "$BUNDLE/apply_implementation.py" --repo "$REPO" --check
python "$BUNDLE/apply_implementation.py" --repo "$REPO" --apply \
  --patch-out /tmp/r17_receipt_implementation_NEW.patch
```

`--check` 默认不修改仓库。应用器要求基线为本地祖先、整个 reader 字节的 Git blob 精确匹配、新测试目标不存在，随后生成完整统一 diff 并运行 `git apply --check`。`--apply` 只改工作树，不 stage/commit/push、不 reset。只改变 reader 的回执 helper 区域及增加一个测试文件；其余既有顶层函数/类还会被 AST 对照确认未改变。

reader 已变化时自动拒绝；不得通过修改 BASE_READER_BLOB 或 force 继续。先核对 Agent 未推送改动或新提交，避免覆盖。patch-out 必须是 checkout 外的新文件。

应用后检查 diff，按已有机制同步部署树；保留本包及生成 patch 的哈希和应用器输出。

## 5. Agent 要实际运行的测试

### 5.1 实现单元测试、旧 slice 测试

```bash
unset R17_RECEIPT_TEST_MODULE
# 默认导入真实 checkout/deployment reader，不使用本包独立代码块。
python -m pytest -q \
  "$REPO/stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_receipt_entry_cleanup_unit.py"
```

新测试兼容发布树 `stage2_6_1/runner` 与部署树 `stage2_6_1_runner` 布局。然后运行原 `test_curriculum261_r17_c3_slice_unit.py`，验证已有 108 项及其实际当前数量；不要将新增测试数量代替旧能力回归。

### 5.2 真实 reader CLI 与旧业务副本

```bash
python "$BUNDLE/verify_reader_in_checkout.py" \
  --repo "$REPO" --out /tmp/r17_receipt_cli_NEW
```

它检查固定原 p52 摘要，再复制旧证据执行 14 次真实 CLI：健康、跨目录悬空链接绝对/相对、父目录与末端组合链接、源内 `symlink+..` 现存/缺失目标、非目录祖先两形态、循环链接、重复回执、正常父目录链接、新嵌套路径、cwd 在源内省略回执。所有破坏性参数仅指向新副本；原件前后复核不变。输出保存每次 argv、stdout/stderr、rc、对象状态及结果。

补一项 `cryptorl` 非 root 的真实权限夹具对照；本地 EACCES 单元测试使用明确 errno 注入，不能宣传为本机物理权限测试。

### 5.3 固定环境完整验收

使用既有监护入口及“R17 测试在前”的声明顺序执行稳定候选全量，保存 stdout/stderr/JUnit、独立业务/外层返回码、运行候选身份及监护证据。只读切片本身不重新生成课程；既有全量的固定输入重放按原合同写新测试目录。

复用现有 C3 关联包、byte verifier 和 unshare 双原根隔离；同一旧业务字节与新 reader 建新包，不替换旧包代码或重签旧锚。正例和本轮代表性路径/临时冲突负例都要检查副作用，不能仅看非零返回码。

若出现代码失败，保存现场后回传；不要自动多次重跑筛绿。测试输出写唯一新位置，不能覆盖旧记录。

## 6. 回报与提交

报告给出：实际基线与完整候选 SHA-256；应用 diff；54 项新测试和原 slice 的真实结果；14 次 CLI 结果；完整 WSL 全量和隔离证据；所有未通过/未执行项。将代码错误、环境问题、测试夹具问题分开。

通过后普通开发提交并 push，保留所有历史，不 amend/force-push。推送后打开固定 commit 下的原始 stdout、JUnit、rc、run_record、summary 和新语义回执；不要只给本机 WORK 路径。

本轮不创建最终 A/B，不启动正式链、不读取新正式数据、不恢复隔离身份，不新增 seed/namespace/坐标、不启用备援或条件采样。fresh rt3、Stage 2.6.1、R16 C2 统计 FAIL、C3 PPO Branch D 均不因这份补丁解除。

## 文件

- `implementation/receipt_block.py`：已实现、已局部测试的内联替换块。
- `apply_implementation.py`：精确 blob 保护、完整 diff 生成和应用。
- `tests/test_curriculum261_r17_receipt_entry_cleanup_unit.py`：会随补丁增加到仓库的 54 项单元测试。
- `verify_reader_in_checkout.py`：待实机执行的 14 次 CLI 检查。
- `tests/test_bundle_application.py`：作者侧应用器机械检查，不加入项目全量。
- `evidence/`：实际本地测试证据及执行范围说明。

技术依据：Python 3.11 官方 `os.path.realpath(strict=True)` 与 `os.lstat` 文档。文件内容真实性仍由固定基线和原业务摘要约束；本包不声称自行重放证明业务发生。
