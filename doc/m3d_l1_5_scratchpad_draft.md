# 3D DRAM 作为 L1.5 Scratchpad Tier 的方案说明草案

## 1. 方案摘要

本方案将 3D DRAM 引入 GPU 存储层级，定位为 **L1（SMEM）与 L2 之间的 L1.5 software-managed scratchpad tier**：

`Reg -> SMEM(L1, SRAM) -> L1.5(3D DRAM Scratchpad) -> L2 -> HBM/VRAM`

核心思想：

1. `SMEM` 保持“极低延迟、极高带宽”的热数据工作集。
2. `L1.5 3D scratchpad` 承接容量更大的 warm tile / staging tile。
3. 通过可编程映射策略（`ROW_LOCAL` / `BANK_BALANCED` / `HYBRID`）优化 row-hit 与并发。

---

## 2. 为什么是 L1.5，而不是直接当 L1

3D DRAM 即使近置，也不具备 SRAM 级固定低延迟语义。  
因此更合理的定位是：

1. **不是**透明替代 L1/SMEM；
2. **而是**显式管理的中间层（scratchpad tier）；
3. 配合异步搬运与双缓冲隐藏延迟。

---

## 3. 架构可行性判断

### 3.1 研究原型层面

可行，且具有明确创新性：

1. 解决 SMEM 容量墙；
2. 将可编程地址映射策略与 scratchpad 管理结合；
3. 为编译器/运行时协同优化提供新接口。

### 3.2 真硬件直接落地层面

高风险，尤其是“每 SM 独立 3D scratchpad”方案：

1. 控制器与刷新/时序管理开销大；
2. 面积与功耗压力高；
3. 利用率可能碎片化（不同 SM 负载不均）。

因此建议优先采用：

- **每 cluster/GPC 共享一份 L1.5 scratchpad**（更现实）

---

## 4. RTX4090/3090 条件下是否可做

可以做，方式是 **trace-driven what-if 仿真**：

1. 使用 RTX3090/4090 采集真实 kernel trace（含 `cp.async/LDGSTS` 地址流）。
2. 在模拟器中把多个 SM 人为分组为“逻辑 cluster”。
3. 为每个逻辑 cluster 增加一份 L1.5（3D scratchpad）模型。
4. 比较不同映射策略与容量/带宽/延迟参数下的性能收益。

注意：这属于架构探索，不是对 Hopper 硅实现的等价复现。

---

## 5. 与既有草案的一致性

本方案延续“驱动下发策略 + 控制器执行映射”：

1. 驱动/运行时：维护 `region/page -> policy_id`，下发矩阵参数；
2. 控制器：执行 `PA -> (Tier, Bank, Row, Col)` 映射；
3. 编程层：继续使用策略抽象（如 `m3dMalloc(size, policy)`）。

`cp.async` 的角色保持不变：

1. 用于地址流生成与延迟隐藏评估；
2. 不作为 DRAM 映射执行单元。

---

## 6. 推荐的第一阶段实现路线（MVP）

1. 先实现“逻辑 cluster 共享 L1.5”而非“每 SM 独立 L1.5”；
2. 固定调度策略（如 FR-FCFS），先隔离映射策略收益；
3. 支持三种映射：`ROW_LOCAL`、`BANK_BALANCED`、`HYBRID`；
4. 对 L1.5 参数做敏感性扫描（容量/带宽/延迟/cluster大小）。

---

## 7. 关键实验设计

### 7.1 自变量

1. L1.5 组织：关闭 / 每 cluster 共享（cluster 大小 sweep）
2. 映射策略：`ROW_LOCAL` / `BANK_BALANCED` / `HYBRID`
3. 搬运方式：`ld.global` vs `cp.async`
4. L1.5 参数：容量、端口带宽、访问延迟

### 7.2 指标

1. 性能：kernel time、吞吐、stall 周期；
2. 存储行为：row-hit、bank/tier 冲突、平均与 P95 延迟；
3. 资源效率：L1.5 占用率、命中率、容量利用率；
4. 成本代理：映射矩阵稀疏度 `nnz(A)`。

---

## 8. 风险与边界声明

1. 无法直接获取“真实 H100 cluster 语义 trace”；
2. `VA->PA` 和事务合并（coalescing）建模会影响结果；
3. 结论应写为“RTX trace 驱动的 what-if 架构研究结论”。

---

## 9. 结论

“3D DRAM 作为 L1.5 scratchpad tier”在研究上合理、可行，并且和现有策略化映射草案高度一致。  
在当前硬件条件（RTX3090/4090）下，推荐采用：

- **逻辑 cluster 共享 L1.5 + 策略化映射 + trace-driven 仿真**

作为第一阶段主路线。
