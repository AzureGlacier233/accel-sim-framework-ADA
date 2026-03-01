# 基于 Accel-Sim 的 L1.5 3D Scratchpad GPU 建模草案

## 1. 目标与前提

基于 `doc/m3d_l1_5_scratchpad_draft.md`，在现有 Accel-Sim/GPGPU-Sim 框架上实现：

1. `SMEM(L1)` 与 `L2` 之间新增 `L1.5 3D scratchpad`；
2. 采用“每逻辑 cluster 共享”而非“每 SM 独立”；
3. 支持策略化映射：`ROW_LOCAL` / `BANK_BALANCED` / `HYBRID`；
4. 使用 RTX3090/4090 trace 做 what-if 仿真。

---

## 2. 现有框架关键入口（代码定位）

### 2.1 cluster/SM 组织

1. `-gpgpu_n_clusters`、`-gpgpu_n_cores_per_cluster` 可配置：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc:423`  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc:425`
2. `num_shader = n_clusters * n_cores_per_cluster`：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.h:1603`
3. trace 模式 cluster/core 创建：  
   `gpu-simulator/trace-driven/trace_driven.cc:509`  
   `gpu-simulator/trace-driven/trace_driven.cc:517`

### 2.2 访存主路径

1. global/local load/store 在 `ldst_unit::memory_cycle`：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc:2260`
2. bypass L1D 时请求直接注入互连：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc:2281`  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc:2309`
3. L2/DRAM 在 `gpgpu_sim::cycle` 驱动：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc:1973`

### 2.3 DRAM 控制路径

1. 分区到 DRAM 的主循环：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l2cache.cc:306`
2. DRAM push/cycle/scheduler：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/dram.cc:247`  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/dram.cc:290`
3. FR-FCFS 调度器：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/dram_sched.cc:207`

---

## 3. 建模方案（MVP）

### 3.1 架构抽象

数据路径改为：

`Reg -> SMEM/L1D -> L1.5(3D scratchpad, cluster-shared) -> L2 -> DRAM`

说明：

1. `L1.5` 为 software-managed tier，不替代 SMEM。
2. 对 global/local 访问新增一层路由判断：
   - 命中 L1.5：返回 core；
   - 未命中：发往 L2/DRAM，并回填到 L1.5（可配）。

### 3.2 cluster 共享实现

在 `simt_core_cluster` 挂载一个共享对象（建议新增类 `l15_scratchpad`）：

1. 类成员新增位置：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.h:2664`
2. 构造与初始化位置：  
   `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc:4470`

### 3.3 `ldst_unit` 路由改造

改造 `ldst_unit::memory_cycle`（`shader.cc:2260`）：

1. 在 `bypassL1D` 分支与 `L1D` 分支之前增加 `L1.5` 访问尝试；
2. 请求打上 `l15_hit/l15_miss` 状态用于统计；
3. 未命中再走原有 `m_icnt->push()` 路径。

建议先仅支持 load 的 L1.5 缓存；store 策略可先做 write-through 到下层。

### 3.4 策略映射实现

新增 `policy engine`（建议在 memory 子系统独立模块）：

1. 输入：地址、`policy_id`；
2. 输出：映射后的 `(tier, bank, row, col)` 或等效 hash/bank id；
3. 策略：
   - `ROW_LOCAL`：偏 row hit；
   - `BANK_BALANCED`：偏并发分散；
   - `HYBRID`：折中。

第一版可先做“地址->L1.5 bank/tier”映射，不改 DRAM 本体地址译码。

### 3.5 配置项扩展

在 `memory_config` / `shader_core_config` 增加参数：

1. `-gpgpu_l15_enable`
2. `-gpgpu_l15_size_per_cluster_kb`
3. `-gpgpu_l15_latency`
4. `-gpgpu_l15_banks`
5. `-gpgpu_l15_policy_mode` (`ROW_LOCAL/BANK_BALANCED/HYBRID`)
6. `-gpgpu_l15_fill_policy`

注册入口参考 `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc` 的 option parser 模式。

### 3.6 统计项扩展

新增：

1. `l15_access/l15_hit/l15_miss`
2. `l15_bank_conflict`
3. `l15_queue_stall`
4. 策略命中分布（按 `policy_id`）

---

## 4. RTX4090/3090 上的实验执行方式

### 4.1 逻辑 cluster 建模

你不需要真实 H100 cluster trace，也可做：

1. 保持 `num_shader` 总数不变；
2. 调整 `n_clusters` 与 `n_cores_per_cluster` 组合（例如 `128x1 -> 32x4`）；
3. 用同一 trace 比较不同 cluster 共享方案。

当前 4090 配置基线：  
`gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config:23`  
`gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config:24`

### 4.2 最小实验矩阵

1. `L1.5` 关闭 vs 开启
2. cluster 规模：2/4/8/16 SM
3. 策略：`ROW_LOCAL/BANK_BALANCED/HYBRID`
4. `ld.global` vs `cp.async` 工作负载

---

## 5. 是否需要集成 Ramulator：结论与建议

### 5.1 结论

**阶段一（当前项目）不必强制集成 Ramulator。**  
先在 Accel-Sim 现有 DRAM 模型上完成 L1.5 架构趋势验证，更快、更稳。

### 5.2 原因

1. 你当前核心创新是 “L1.5 scratchpad + 策略映射 + cluster 共享”；
2. 这些改造主要发生在 core/cluster/L1-L2 路径，不依赖更换 DRAM 后端才能成立；
3. Accel-Sim 已有 DRAM 时序与 FR-FCFS 可用于 first-order 对比。

### 5.3 何时值得集成 Ramulator

当你需要回答以下问题时，再接入更合理：

1. 3D DRAM 的 tier-level 细粒度时序差异；
2. 更复杂的 row policy/refresh/thermal 影响；
3. 对绝对延迟与 bank/tier 行为做更高保真结论。

### 5.4 集成接口建议（二期）

在 `memory_partition_unit::dram_cycle` 位置抽象 DRAM backend 接口：

1. 保留现有 `dram_t` 作为 default backend；
2. 新增 `ramulator_backend` 实现 `push/cycle/return_queue`；
3. 切换开关由 config 控制。

关键挂接位置：  
`gpu-simulator/gpgpu-sim/src/gpgpu-sim/l2cache.cc:306`  
`gpu-simulator/gpgpu-sim/src/gpgpu-sim/l2cache.cc:333`

---

## 6. 推荐路线（执行优先级）

1. **P0**：L1.5 cluster-shared 结构 + 统计打通（不接 Ramulator）
2. **P1**：三策略映射 + 参数扫描 + 消融实验
3. **P2**：如需高保真 DRAM 论文点，再做 Ramulator backend

---

## 7. 一句话结论

对你当前目标，**先改 Accel-Sim 本体做 L1.5 建模最合理，Ramulator 不是第一阶段必需项**；  
Ramulator 更适合作为第二阶段“提高 3D DRAM 物理时序真实性”的增强模块。
