# Accel-Sim M3D + L1.5 改动说明（对照规划文档）

## 1. 目的

本文件用于对照以下两份方案文档，解释已实现改动：

- `doc/accelsim_m3d_l15_modeling_plan.md`
- `doc/m3d_l1_5_scratchpad_draft.md`

---

## 2. 已落地提交与仓库

### 2.1 框架根仓库（配置层）

- 仓库：`/home/zhanglx/accel-sim-framework`
- 分支：`dev`
- 提交：`d774e9f`
- 改动文件：
  - `gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config`

### 2.2 gpgpu-sim 子仓库（模型实现层）

- 仓库：`/home/zhanglx/accel-sim-framework/gpu-simulator/gpgpu-sim`
- 分支：`dev`
- 提交：`9f761655`
- 改动文件：
  - 新增：`src/gpgpu-sim/l15_scratchpad.h/.cc`
  - 新增：`src/gpgpu-sim/m3d_mapping_policy.h/.cc`
  - 修改：`src/gpgpu-sim/shader.h/.cc`
  - 修改：`src/gpgpu-sim/gpu-sim.h/.cc`
  - 修改：`src/gpgpu-sim/dram.h/.cc`
  - 修改：`src/gpgpu-sim/dram_sched.cc`

---

## 3. 与 `accelsim_m3d_l15_modeling_plan.md` 的对照

### 3.1 L1.5 架构抽象与 cluster 共享（已实现）

- 按 cluster 挂载共享 L1.5：
  - `src/gpgpu-sim/shader.h`（`simt_core_cluster::m_l15` / `get_l15()`）
  - `src/gpgpu-sim/shader.cc`（cluster 构造、析构、`core_cycle`）
- 新增 L1.5 模型类：
  - `src/gpgpu-sim/l15_scratchpad.h/.cc`
  - 支持 `access/fill/cycle`、LRU 容量管理、bank 冲突与统计。

### 3.2 `ldst_unit` 路由与命中返回（已实现）

- 在 `ldst_unit::memory_cycle` 中对 load 增加 L1.5 probe：
  - hit：进入 `m_l15_hit_queue`，按 `gpgpu_l15_latency` 延迟完成寄存器/scoreboard 释放；
  - miss：走原有 L1/L2/DRAM 路径；
  - reservation fail：计入 bank conflict / stall。
- 在 `ldst_unit::cycle` 增加 `L15_hit_queue_cycle(...)`。
- 在 response path 增加 L1.5 fill（`fill_policy == on_miss`）。

### 3.3 L1.5 参数化（已实现）

- 新增并注册参数：
  - `-gpgpu_l15_enable`
  - `-gpgpu_l15_size_per_cluster_kb`
  - `-gpgpu_l15_line_size`
  - `-gpgpu_l15_latency`
  - `-gpgpu_l15_banks`
  - `-gpgpu_l15_fill_policy`
  - `-gpgpu_l15_policy_mode`
- 代码位置：
  - `src/gpgpu-sim/shader.h`（默认值与配置打印）
  - `src/gpgpu-sim/gpu-sim.cc`（option parser 注册）
- 配置示例已写入：
  - `gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config`

### 3.4 策略映射（L1.5 与 MC 层，已实现）

- L1.5 内建三策略 bank 映射：
  - `ROW_LOCAL / BANK_BALANCED / HYBRID`
  - 代码：`src/gpgpu-sim/l15_scratchpad.cc`
- MC 层新增 `m3d_mapping_policy`：
  - 模式：`ROW_LOCAL / BANK_BALANCED / HYBRID / REGION_TABLE`
  - 可加载 region-policy CSV 表；
  - 输出 `bank/tier_tag/policy_id`；
  - 代码：`src/gpgpu-sim/m3d_mapping_policy.h/.cc` + `dram.cc`

### 3.5 DRAM 控制器调度策略（已实现）

- 新增调度器类型：
  - `DRAM_M3D_AWARE_FRFCFS`
  - 定义：`src/gpgpu-sim/gpu-sim.h`
- 在 `frfcfs_scheduler::schedule` 中增加 M3D-aware 打分分支：
  - score = row-hit 权重 + bank/tier balance 权重 + age 权重；
  - 权重配置：
    - `-gpgpu_m3d_sched_weight_rowhit`
    - `-gpgpu_m3d_sched_weight_bank_balance`
    - `-gpgpu_m3d_sched_weight_age`
  - 代码：`src/gpgpu-sim/dram_sched.cc`

### 3.6 统计项（已实现）

- Shader 统计新增：
  - `gpgpu_n_l15_access/hit/miss/reservation_fail/bank_conflict`
  - `gpgpu_n_l15_hit_latency_cycles`
  - `gpgpu_l15_hit_rate`
  - 代码：`src/gpgpu-sim/shader.h/.cc`
- DRAM 统计新增：
  - `m3d_policy_use`
  - `m3d_policy_row_hits`
  - `m3d_policy_bank_conflicts`
  - 代码：`src/gpgpu-sim/dram.h/.cc`

---

## 4. 与 `m3d_l1_5_scratchpad_draft.md` 的一致性说明

已对齐草案中的核心思想：

1. **层级定位**：L1.5 作为 `SMEM/L1` 与 `L2` 之间中间层（cluster 共享）。
2. **策略化映射**：支持 `ROW_LOCAL/BANK_BALANCED/HYBRID`，并扩展了 region-table 控制。
3. **控制器策略**：在 FR-FCFS 基础上加入 M3D-aware 评分调度。
4. **what-if 可配置性**：关键参数均已通过 config 可控，可做 sweep。

---

## 5. 按任务单（`accelsim_m3d_l15_tasklist.md`）完成度

- T1 配置参数：完成
- T2 L1.5 类：完成
- T3 cluster 共享挂载：完成
- T4 ldst 接入（load 优先）：完成
- T5 统计与日志：完成
- T6 策略引擎（3 策略 + MC 策略）：完成
- T7 cluster sweep 支持：未单独提供自动化脚本（可用现有配置手动改）
- T8 实验自动化脚本：未实现
- T9 DRAM backend 抽象：未实现
- T10 Ramulator backend：未实现

---

## 6. 当前边界与已知限制

1. 尚未完成完整编译/回归验证（环境缺少 `nvcc`，未跑 end-to-end）。
2. L1.5 目前优先覆盖 load 路径；store 沿用原路径（未做复杂一致性增强）。
3. MC mapping 当前主要重映射 bank 与 tier_tag，row/col 仍以原译码为主。
4. 配置文件里 M3D/L1.5 默认仍为关闭态（便于 baseline 对照）。

---

## 7. 快速核对命令

```bash
# 根仓库提交
git -C /home/zhanglx/accel-sim-framework show --name-status --oneline d774e9f

# gpgpu-sim 子仓库提交
git -C /home/zhanglx/accel-sim-framework/gpu-simulator/gpgpu-sim show --name-status --oneline 9f761655

# 查看 L1.5 / M3D 参数是否在配置中
rg -n "gpgpu_l15|m3d" /home/zhanglx/accel-sim-framework/gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config
```

