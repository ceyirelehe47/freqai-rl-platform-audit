# 勘误（R17C2SelectionCalibrationConsumerIntegration-v1）

1. delivery/REPORT.md §5 所称"副本见 WORK/input_pack.zip"与事实不符：S5 归档时 cp 源路径笔误
   （把 /mnt/e/trading/R17_C2_Selection_Calibration_Consumer_v1/ 下嵌套路径当作 zip 位置），zip
   副本未随 delivery 入档；且 delivery/input_pack.sha256 为 0 字节空文件（sha256sum 对缺失文件的
   重定向产物）。两者均已封入 E=3569d87a06c2c5a2b596cde3955a53fa51129439 的导出 manifest，按导出完整性合同不回改已封存成员。
   输入包真实性不受影响：原件三处可验（服务器 /root/download/、Windows E 盘工作目录、WSL
   work/packages/r17_c2_consumer_v1），包 sha256 f600633e8ead87e8开头，且
   delivery/package_checksum.txt 已记录 SHA256SUMS 65/65 OK。
2. delivery/REPORT.md §4 "证据 E：PENDING" 的真实值：E=3569d87a06c2c5a2b596cde3955a53fa51129439（REPORT.md 按 RUNBOOK
   在 E 之前写入，不回改）。
3. 本勘误仅新增本文件；不修改任何 delivery 成员、源码、测试或历史对象。
