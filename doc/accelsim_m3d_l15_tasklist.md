# Accel-Sim L1.5(3D Scratchpad) 实现任务单

## 0. 使用说明

本任务单对应方案文档：

- `doc/accelsim_m3d_l15_modeling_plan.md`
- `doc/m3d_l1_5_scratchpad_draft.md`

执行顺序建议：`P0 -> P1 -> P2`。  
其中 `P0` 是最小可运行版本（MVP），`P1` 是策略与实验强化，`P2` 是 Ramulator 集成（可选二期）。

---

## P0：最小可运行版本（必须完成）

## T1. 新增配置参数（L1.5 开关与容量/延迟）

### 目标

在配置文件中可控开启/关闭 L1.5，并设置核心参数。

### 修改点

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.h`
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc`
3. `gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config`（新增示例配置）

### 参数建议

1. `-gpgpu_l15_enable`
2. `-gpgpu_l15_size_per_cluster_kb`
3. `-gpgpu_l15_latency`
4. `-gpgpu_l15_banks`
5. `-gpgpu_l15_fill_policy`（none/on_miss）

### 验收标准

1. 启动日志能打印 L1.5 参数。
2. 关闭开关时性能与 baseline 一致（误差在噪声范围内）。

---

## T2. 新建 L1.5 模型类（cluster 共享对象）

### 目标

实现一个最简 `l15_scratchpad` 类，支持访问、填充、周期推进与统计。

### 建议新增文件

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.h`
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.cc`

### 最小接口

1. `access(addr, is_write)` -> `HIT/MISS/RESERVATION_FAIL`
2. `fill(addr, line_size)`
3. `cycle()`
4. `print_stats(fp)`

### 验收标准

1. 单元测试或最小 mock 下 HIT/MISS 行为正确。
2. 统计计数（access/hit/miss）一致。

---

## T3. 挂载到 cluster（每 cluster 一份 L1.5）

### 目标

让同一 cluster 的多个 core 共享同一 L1.5 实例。

### 修改点

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.h`
   - 在 `simt_core_cluster` 增加 `m_l15` 成员与 getter
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc`
   - 在 `simt_core_cluster` 构造函数初始化 `m_l15`
   - 在析构中释放 `m_l15`

### 验收标准

1. 每 cluster 仅创建一个 L1.5 对象。
2. cluster 内 core 访问同一对象（地址命中可复用）。

---

## T4. 接入 ldst 访问路径（先做 load）

### 目标

在 global/local 访问路径中加入 L1.5 访问逻辑。

### 主要入口

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc`
   - `ldst_unit::memory_cycle(...)`
   - 必要时 `ldst_unit::cycle(...)`

### 行为建议

1. 对 load：
   - 先 probe L1.5
   - hit：按 `l15_latency` 延迟返回（可先简化为固定周期）
   - miss：走原路径到 L2/DRAM，返回后按策略决定是否 fill L1.5
2. 对 store：
   - P0 先保持原行为（或 write-through），避免一致性复杂化

### 验收标准

1. 功能正确（程序输出不变）。
2. 开启 L1.5 后统计可见 `l15_hit/l15_miss`。

---

## T5. 统计与日志

### 目标

输出可用于论文图表的最小指标。

### 修改点

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc`（或统计汇总路径）
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc`（统一打印）

### 最小统计

1. `l15_access`
2. `l15_hit`
3. `l15_miss`
4. `l15_hit_rate`
5. `l15_bank_conflict`（若实现 bank）

### 验收标准

1. stats 文件可解析为 CSV（建议脚本化）。
2. 与开关状态一致（关闭时计数应为 0）。

---

## P1：策略化映射与实验增强（建议完成）

## T6. 策略引擎接入（ROW_LOCAL/BANK_BALANCED/HYBRID）

### 目标

在 L1.5 内引入策略化 bank/tier 映射逻辑。

### 修改点

1. `l15_scratchpad.*`（新增策略枚举与地址映射函数）
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.h/.cc`（策略参数）
3. 配置文件新增：`-gpgpu_l15_policy_mode`

### 验收标准

1. 三种策略可切换运行。
2. 统计能区分策略效果（hit/conflict/latency）。

---

## T7. 逻辑 cluster sweep 支持

### 目标

支持在同一 trace 上切换 `n_clusters * n_cores_per_cluster` 组合，模拟不同共享粒度。

### 修改点

1. 配置脚本（建议新增 experiment driver）
2. `gpu-simulator/configs/tested-cfgs/SM89_RTX4090/` 下复制多套配置

### sweep 建议

1. `128x1`（baseline）
2. `64x2`
3. `32x4`
4. `16x8`

### 验收标准

1. 总 SM 数保持一致时可稳定运行。
2. 输出结果按 cluster 粒度可比较。

---

## T8. 工作负载与对照实验脚本

### 目标

自动化运行最小实验矩阵，产出可画图数据。

### 最小矩阵

1. L1.5：on/off
2. policy：3种
3. copy path：`ld.global` vs `cp.async`

### 产出

1. 汇总 CSV
2. 图表脚本（延迟、吞吐、hit/conflict）

### 验收标准

1. 一条命令可跑完整矩阵（可分批）。
2. 失败任务可重跑（断点续跑）。

---

## P2：Ramulator 集成（二期，可选）

## T9. 抽象 DRAM backend 接口

### 目标

将现有 `dram_t` 路径抽象为可替换后端。

### 修改点

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l2cache.cc`
   - `memory_partition_unit::dram_cycle()`
2. 新增接口文件（例如 `dram_backend.h/.cc`）

### 验收标准

1. 默认后端仍是现有 `dram_t`，回归不退化。
2. 后端切换由 config 控制。

---

## T10. Ramulator backend 实现

### 目标

接入 Ramulator 作为 DRAM 时序后端。

### 输入输出契约

1. 输入：`mem_fetch` 请求（地址、读写、时间戳）
2. 输出：完成事件（回到分区 return queue）

### 验收标准

1. 功能正确，事件顺序与时序一致。
2. 与默认后端可做 A/B 比较。

---

## 交付检查清单（最终）

1. `L1.5 on/off` 功能跑通
2. cluster-shared 行为正确
3. 三策略可切换
4. 实验矩阵脚本可复现
5. 文档与配置齐全
6. （可选）Ramulator 后端可运行

---

## 推荐执行顺序（两周冲刺版）

1. 第 1-2 天：T1
2. 第 3-4 天：T2
3. 第 5-6 天：T3
4. 第 7-9 天：T4
5. 第 10 天：T5
6. 第 11-13 天：T6
7. 第 14 天：T7/T8 框架搭建

Ramulator（T9/T10）放到下一轮迭代。
