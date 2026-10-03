# deploy_extra_modules 计数口径说明(reviewer gate1 P3-2 文档层更正)

`report.json` 的 `deploy_extra_modules` 数组共 **68 项**,其中
**67 项为 deploy-only src 模块文件**(generator_api 等),另 1 项
为 `__pycache__` **目录项**(采集脚本用 `os.listdir` 未过滤目录)。

- 与 R4/本轮差分 record 的 `deploy_extra_modules` 对拍口径 =
  **67 个模块文件**,集合精确相等(reviewer gate1 T4 双重对拍:
  record 面 325 成员 + extra 67 模块,src/tests/runner 全同)。
- `__pycache__` 为运行副产物,不是代码身份成员;SUMMARY.md 中
  "68 个 deploy-only src 模块" 的表述按本说明更正为
  "67 个模块文件(+1 个 __pycache__ 目录项)"。
- 本说明为口径澄清;不改写已提交的 report.json 数据本身
  (数组内容真实,目录项如实列示)。
