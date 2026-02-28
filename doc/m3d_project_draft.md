# 可编程 3D DRAM 映射系统项目草案（完整版）

## 1. 项目名称

**Compiler-Orchestrated Programmable 3D DRAM Mapping System**  
（编译器协同的可编程 3D DRAM 映射系统）

---

## 2. 研究背景与问题定义

面向 AI 工作负载（GEMM、Conv、Attention）的内存访问同时存在两种需求：

1. 保持行局部性（提高 row-buffer hit，降低 ACT/PRE 开销）。
2. 提高 bank/tier 并发（降低冲突与热点，提升带宽利用率）。

传统固定映射难以同时兼顾两者。  
因此本项目目标是构建一个**可编程映射框架**，让系统可根据工作负载特征选择不同映射策略。

---

## 3. 目标与范围

### 3.1 总目标

构建“**驱动可配置 + 控制器执行**”的 3D DRAM 映射系统原型，并提供上层编程抽象。

### 3.2 MVP 范围

1. 支持三种策略：`ROW_LOCAL`、`BANK_BALANCED`、`HYBRID`。
2. 配置粒度先做“页/缓冲区级”，不做指令级动态切换。
3. 先不做运行时数据迁移（避免复杂度失控）。
4. 用 trace-driven + DRAM 模型完成第一阶段验证。

### 3.3 非目标（当前阶段）

1. 不宣称在商用闭源 GPU 上实现真实硬件替换。
2. 不把 `cp.async` 当作控制器映射执行单元。

---

## 4. 理论基础（对齐论文）

### 4.1 Rotaru 侧（DRAM 映射）

1. 地址映射可表示为 GF(2) 上的 BIM（Binary Integer Matrix）。
2. row miss 与映射矩阵及访问差分向量相关。
3. 映射优化需要同时考虑：  
   - row miss 最小化  
   - 硬件复杂度（矩阵稀疏度/1 的个数）

### 4.2 Zhou 侧（Linear Layout）

1. 布局统一建模为 GF(2) 线性映射。
2. 可通过线性代数统一处理布局变换与冲突优化。
3. “最优 swizzling”的关键思想可迁移为 bank/tier 分散策略设计方法。

### 4.3 本项目融合点

1. 用 Rotaru 思路优化 row locality（`ROW_LOCAL`）。
2. 用 Zhou 的冲突子空间思想优化 bank/tier 分散（`BANK_BALANCED`）。
3. 用 `HYBRID` 在两者间做可调折中。

---

## 5. 系统分层架构

### 5.1 编程层（CUDA/Triton）

程序员只表达“访问意图”，不手写地址位运算。

建议接口：

```cpp
enum M3DPolicy {
  ROW_LOCAL = 0,
  BANK_BALANCED = 1,
  HYBRID = 2
};

void* m3dMalloc(size_t bytes, M3DPolicy policy);
void  m3dFree(void* ptr);
```

### 5.2 运行时/驱动层

1. 维护 `region/page -> policy_id` 绑定表。
2. 将 `policy_id` 对应矩阵参数写入控制器寄存器/策略表。
3. 对应用暴露稳定 API，屏蔽硬件细节。

### 5.3 控制器层（核心执行层）

执行真实映射：

`PA -> (Tier, Bank, Row, Col)`

控制器按 `policy_id` 选择矩阵 `A_policy` 执行 GF(2) 运算。

### 5.4 仿真验证层

1. 通过 `cp.async/LDGSTS` 生成高质量地址流（只作载体）。
2. 对 trace 做事务级 coalescing。
3. 将地址流送入 DRAM 模型，评估策略收益。

---

## 6. 三种策略定义

### 6.1 `ROW_LOCAL`

目标：最大化 row hit，降低平均延迟。  
特点：弱分散、强局部性。

### 6.2 `BANK_BALANCED`

目标：最大化 bank/tier 并发与均衡。  
特点：强分散、吞吐优先。

### 6.3 `HYBRID`

目标：在局部性与并发之间取得折中。  
典型思想：

1. 低位偏向 `Col`（保局部性）。
2. 中位经 XOR 映射到 `Bank/Tier`（增并发）。
3. 高位承担 `Row`（保证容量与组织）。

---

## 7. 与 FR-FCFS/FRFS 的区别与协同

1. 映射策略（`ROW_LOCAL/BANK_BALANCED/HYBRID`）决定地址“落在哪里”。
2. 调度策略（`FR-FCFS/FRFS`）决定请求“先服务谁”。
3. 两者正交、协同，不互相替代。
4. 推荐实验时固定调度策略，先看映射收益；再做映射+调度联合收益分析。

---

## 8. 数学建模与优化目标

定义映射矩阵 `A` 后，可采用加权目标：

`J(A) = α * RowHit(A) + β * Balance_bank_tier(A) - γ * Cost(A)`

其中：

1. `RowHit(A)`：行命中收益（越高越好）。
2. `Balance_bank_tier(A)`：bank/tier 分散与均衡收益。
3. `Cost(A)`：硬件实现代价，建议使用 `nnz(A)`（矩阵 1 的个数）作为代理。

求解路线：

1. 小规模 trace：ILP 做上界与校准。
2. 大规模 trace：Greedy + 稀疏化后处理。

---

## 9. `cp.async` 的角色边界（必须在文稿中明确）

`cp.async` 可用于：

1. 产生高并发访问流。
2. 评估延迟隐藏能力。

`cp.async` 不用于：

1. 直接替代 DRAM 控制器地址映射。
2. 宣称实现真实硬件物理映射控制。

建议统一表述为：

**software-emulated mapping（软件模拟映射）**

---

## 10. 实验计划

### 10.1 自变量

1. 映射策略：`Linear`、`ROW_LOCAL`、`BANK_BALANCED`、`HYBRID`
2. 指令形态：`ld.global` vs `cp.async`
3. 内存配置：2D baseline / 3D medium-lat / 3D high-lat
4. 负载类型：顺序、跨步、随机、交织、张量核

### 10.2 指标

1. row-hit rate
2. bank/tier conflict rate
3. 平均延迟与 P95 延迟
4. 有效带宽
5. stall 周期与 kernel 吞吐
6. 策略硬件代价（`nnz(A)`）

### 10.3 消融实验

1. `HYBRID` 去掉低位局部性约束
2. `HYBRID` 去掉 bank/tier XOR 分散
3. 去掉 coalescing（验证错误建模影响）
4. open-loop 与 closed-loop 时间回填对比

---

## 11. 工程实施计划（里程碑）

### 阶段 A：基础设施（第 1-2 周）

1. 跑通基线 trace 与仿真流程。
2. 定义策略枚举、配置文件、日志格式。

### 阶段 B：策略求解与编码（第 3-4 周）

1. 完成 `ROW_LOCAL`、`BANK_BALANCED`、`HYBRID` 矩阵生成。
2. 完成策略表与矩阵参数加载。

### 阶段 C：接口与接线（第 5-6 周）

1. 实现 `m3dMalloc` 抽象与 region-policy 绑定。
2. 完成 trace coalescing 与 DRAM 模型输入适配。

### 阶段 D：实验与论文（第 7-8 周）

1. 完成主实验与消融实验。
2. 形成图表、结论、威胁分析。

---

## 12. 风险与应对

1. `VA != PA` 带来映射不确定性。  
   方案：明确假设并做敏感性分析。

2. 事务粒度错误会夸大压力。  
   方案：强制 coalescing 后再送 DRAM 模型。

3. 单一策略在不同 workload 下不稳。  
   方案：保留多策略并建立策略选择规则。

4. 动态重配置代价高。  
   方案：MVP 阶段采用静态绑定，后续再研究迁移。

---

## 13. 预期产出

1. 一套可编程 3D DRAM 映射原型（驱动配置 + 控制器执行）。
2. 一套上层编程抽象（策略化分配接口）。
3. 一组完整实验结果（映射收益、调度协同、`cp.async` 边界）。
4. 一篇可投稿的系统/架构方向论文草稿。

---

## 14. 一句话总结

本项目以 GF(2) 线性映射为统一框架，将 Rotaru 的 row-locality 优化与 Zhou 的冲突优化思想融合，形成可编程策略化的 3D DRAM 映射系统；在实现上采用“**驱动下发策略、控制器执行映射**”的工程路径，并以 `cp.async` 作为实验载体而非控制器替代。
