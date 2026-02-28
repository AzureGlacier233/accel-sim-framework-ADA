# 可编程 3D DRAM 映射策略设计说明（正式草案）

## 1. 文档目的

本文定义两类可编程映射策略：

- `ROW_LOCAL`
- `BANK_BALANCED`

并说明其与常规内存调度策略（如 `FR-FCFS` / `FRFS`）的关系、区别与协同方式。本文同时给出面向驱动与控制器的最小可行落地方案（MVP）。

---

## 2. 概念分层

### 2.1 映射策略（Mapping Policy）

映射策略回答的问题是：

> 一个物理地址 `PA` 应该映射到哪个 `(Tier, Bank, Row, Col)`。

其本质是地址变换函数（通常可写为 GF(2) 上的线性/XOR 变换）：

`f_map: PA -> (Tier, Bank, Row, Col)`

### 2.2 调度策略（Scheduling Policy）

调度策略回答的问题是：

> 请求队列里，下一条先服务谁。

例如 `FR-FCFS`（First Ready, First Come First Serve）优先服务“可立即发射、且倾向行命中”的请求。

---

## 3. `ROW_LOCAL` 策略定义

### 3.1 目标

最大化 `row-buffer hit`，降低 `ACT/PRE` 开销，优化平均访问延迟。

### 3.2 典型映射思想

- 低位优先映射到 `Col`，保持 cache line 内连续访问。
- 尽量让相邻地址在短时间窗口内落在同一 `Bank` 的同一 `Row`。
- 对 `Bank/Tier` 的打散较弱或受限。

### 3.3 预期效果

- 优点：延迟较低、row 命中率高。
- 风险：并发度不足，热点 bank/tier 可能更明显。

---

## 4. `BANK_BALANCED` 策略定义

### 4.1 目标

最大化 bank/tier 并行度与负载均衡，提升吞吐和带宽利用率。

### 4.2 典型映射思想

- 保持基本列位语义后，对 `Bank/Tier` 位引入 XOR swizzle。
- 常见形式：`Bank_ID = MidBits XOR HighBits`（示意形式）。
- 使顺序访问在跨 cache line 时更容易分散到不同 bank/tier。

### 4.3 预期效果

- 优点：并发高、带宽利用率高、热点缓解。
- 风险：row 局部性下降，平均单次访问延迟可能上升。

---

## 5. 与 `FR-FCFS/FRFS` 的区别

### 5.1 本质区别

- `ROW_LOCAL` / `BANK_BALANCED`：决定“地址落点”（映射层）。
- `FR-FCFS` / `FRFS`：决定“服务次序”（调度层）。

二者是正交关系，不可替代。

### 5.2 关系

1. 映射策略决定可形成多少行命中机会、并发机会。
2. 调度策略在这些机会之上做局部最优选择。
3. 映射差时，调度再好也受上限约束；映射好时，调度收益更易发挥。

---

## 6. 系统落地位置：驱动 vs 控制器

### 6.1 控制器职责（必须）

控制器执行真实地址映射：

`PA -> (Tier, Bank, Row, Col)`

这一步必须在控制器（或其等效硬件模型）中实现，才是真正物理映射。

### 6.2 驱动职责（配置与绑定）

驱动不执行映射本身，而是：

1. 选择策略（`policy_id`）。
2. 将 `policy_id` 对应矩阵参数写入控制器寄存器/策略表。
3. 维护地址区间（或页）与 `policy_id` 的绑定关系。

结论：**驱动负责“下发策略”，控制器负责“执行映射”。**

---

## 7. 建议的软件抽象（MVP）

```cpp
enum M3DPolicy {
  ROW_LOCAL = 0,
  BANK_BALANCED = 1,
  HYBRID = 2
};

void* m3dMalloc(size_t bytes, M3DPolicy policy);
void  m3dFree(void* ptr);
```

程序员只表达访问意图，不需要手写地址 XOR 位操作。

---

## 8. 与 `cp.async` 的关系（边界）

`cp.async` 可用于：

- 生成高并发地址流（如 `LDGSTS` 的 global source address）。
- 评估延迟隐藏效果。

`cp.async` 不应被表述为：

- 已直接实现真实 DRAM 地址映射控制。

因此在论文和报告中建议使用术语：

- `software-emulated mapping`（软件模拟映射）

---

## 9. 推荐的实验对比最小集合

1. 映射策略：`ROW_LOCAL` vs `BANK_BALANCED` vs `HYBRID`
2. 调度策略：固定 `FR-FCFS`（或固定其他调度）比较映射收益
3. 负载：顺序/跨步/随机/张量核
4. 指标：row-hit、bank冲突率、平均延迟、P95延迟、有效带宽、吞吐

这样可清晰分离：

- 映射收益
- 调度收益
- 二者协同收益

---

## 10. 结论

`ROW_LOCAL` 与 `BANK_BALANCED` 是两种面向不同目标的映射策略：

- 前者偏延迟与行命中；
- 后者偏并发与吞吐。

它们与 `FR-FCFS/FRFS` 的关系是“映射层 + 调度层”的协同，而非替代。工程实现上，最合理路径是：

**驱动配置策略 + 控制器执行映射**。
