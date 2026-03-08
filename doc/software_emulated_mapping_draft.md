# Software-Emulated Mapping 草案（基于真实硬件 Trace）

## 1. 目的

本文定义在“不修改 GPGPU-Sim 架构实现”的前提下，如何使用真实硬件 trace 做 `software-emulated mapping` 实验，并明确其边界、合规要求与报告口径。

---

## 2. 什么是“地址重写”

地址重写（address rewriting）是指：

1. 对 trace 中每条内存请求地址 `A` 应用一个可重复的映射函数 `g`；
2. 得到新地址 `A' = g(A, policy)`；
3. 其余字段尽量保持不变（请求顺序、读写类型、请求大小、时间戳语义）。

该方法本质是“软件层模拟不同布局/映射策略对地址流的影响”，不是硬件控制器真实执行的物理地址译码。

---

## 3. 对真实硬件 Trace 预处理是否“合法”

## 3.1 学术与工程上可接受（在满足披露条件时）

可接受，前提是你明确声明：

1. 方法是 `software-emulated mapping`；
2. 不是在宣称“真实硬件控制器已实现该映射”；
3. 结果用于趋势分析、策略比较和敏感性研究。

该边界与现有文档一致：

1. `cp.async` 可用于高并发地址流与延迟隐藏评估；
2. `cp.async` 不应被表述为直接实现 DRAM 物理映射控制；
3. 控制器执行真实映射，驱动/软件负责策略下发与绑定。

---

## 3.2 合规与可复现要求（建议写进方法章节）

1. 保留原始 trace，不覆盖原文件。
2. 预处理脚本版本固定并可回放（commit/hash）。
3. 输出 `raw -> rewritten` 映射日志或哈希校验。
4. 在论文中区分“原始 trace 结果”和“重写 trace 结果”。
5. 若 trace 受 EULA/NDA 约束，遵守分发与脱敏要求。

---

## 3.3 不建议或不合格做法

1. 未披露地修改请求顺序并宣称“仅改映射策略”。
2. 同时修改地址和时间戳，但不说明时序模型假设。
3. 用重写结果宣称“硬件已经可实现同等效果”。

---

## 4. `software-emulated mapping` 最小实验流程

## 4.1 输入

1. 真实硬件 trace（建议含 `ld.global` 和/或 `cp.async` 场景）。
2. 策略集合：`ROW_LOCAL`、`BANK_BALANCED`、`HYBRID`。
3. 基线策略：`IDENTITY`（不重写地址）。

---

## 4.2 预处理步骤

1. 读取 trace 请求流 `(t, op, size, addr, ...)`。
2. 地址对齐到 line 粒度（例如 128B）：`line = addr >> 7`。
3. 按 policy 对 line 号做位级变换，得到 `line'`。
4. 还原地址：`addr' = (line' << 7) | (addr & 0x7f)`。
5. 写出新 trace，保留非地址字段不变。

---

## 4.3 建议的策略函数（示意）

1. `IDENTITY`  
   `line' = line`
2. `ROW_LOCAL`  
   目标是增强局部连续 line 在同一行的概率，减少行切换。
3. `BANK_BALANCED`  
   示例：`line' = line ^ (line >> k1) ^ (line >> k2)`，提升 bank 分散。
4. `HYBRID`  
   组合 coarse（row chunk）与 fine（xor swizzle）位。

说明：示意函数用于策略对比，参数应固定并公开，避免“隐式调参”。

---

## 4.4 仿真与汇总

1. 对每个 policy 生成一份 trace。
2. 使用同一 `gpgpusim.config`（或同一参数组）运行。
3. 采集统一指标：
   `gpu_sim_cycle`、`l15_hit_rate`、`m3d_policy_*`、延迟/吞吐指标。
4. 输出对照表与统计显著性（均值/方差或置信区间）。

---

## 5. 报告口径模板（可直接放论文）

> We evaluate mapping policies using software-emulated mapping on real hardware traces.  
> Address streams are rewritten offline by deterministic policy functions, while preserving request order and non-address metadata.  
> This setup does not claim hardware controller implementation; it is used to isolate mapping sensitivity and performance trends.

中文建议表述：

1. 本实验采用基于真实硬件 trace 的软件模拟映射方法。
2. 通过离线地址重写比较策略差异，保持请求顺序与非地址字段一致。
3. 结果用于评估映射策略趋势，不等价于真实控制器物理映射实现。

---

## 6. 与当前仓库文档的一致性

与以下文档口径一致：

1. `doc/m3d_policy_design.md`：控制器执行真实映射，`cp.async` 不是映射执行单元。
2. `doc/m3d_project_draft.md`：可使用 `software-emulated mapping` 术语。
3. `doc/accelsim_m3d_l15_tasklist.md`：`ld.global` 与 `cp.async` 可作为对照自变量。

---

## 7. 结论

你可以对真实硬件 trace 做地址重写预处理来评估策略，但必须：

1. 披露为 `software-emulated mapping`；
2. 不宣称替代硬件控制器映射实现；
3. 保证流程可复现、可审计、可追踪。
