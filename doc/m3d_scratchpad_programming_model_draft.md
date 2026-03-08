# M3D Scratchpad Programming Model 正式草案

## 1. 立场与目标

本文提出一种面向 Monolithic 3D DRAM 的软件可见编程抽象：`M3D scratchpad`。

该抽象不要求程序员显式控制物理地址译码，也不把研究重点放在内存控制器策略枚举上，而是将 3D DRAM 暴露为一种：

1. 作用域高于单个 thread block 的显式托管存储层；
2. 延迟高于 `shared memory`、低于常规远端 `global memory` 的中间层；
3. 以 `channel` 为最高层级可见并行单位的逻辑存储空间；
4. 依赖显式异步搬运、同步与软件流水线实现高效使用的 scratchpad。

该方向的核心目标不是替代真实硬件地址映射，而是建立一种与 `CUDA shared memory`、`Distributed Shared Memory`、`Triton tensor descriptor` 和 `Gluon linear layout` 风格一致的可编程接口，使程序员能够直接表达：

1. 数据应驻留在哪个中间层；
2. 数据何时从 `global` 搬入该中间层；
3. 数据如何以 `channel` 感知的方式分块和复用；
4. 线程块或 warp 如何围绕该中间层组织流水线。

---

## 2. 为什么采用 `channel` 作为最高层级抽象

本文明确采用 `channel` 而非更细粒度的内部层次作为 3D DRAM 的程序可见最高层级，原因如下：

1. 公开硬件资料中，堆叠 DRAM 往往首先按 `channel` 组织系统级并行性，再向下细分到 `bank/row/col`。Micron HBM2E/HBM3E 与 Samsung HBM2 官方资料均将高带宽来源描述为多个独立 `channel` 并行提供。  
   - Micron HBM3E: https://jp.micron.com/products/memory/hbm/hbm3e  
   - Samsung HBM2 Flarebolt: https://semiconductor.samsung.com/us/dram/hbm/hbm2-flarebolt/
2. NVIDIA CUDA 官方文档已证明“高于单个 block 的共享存储层”可以通过 cluster 范围暴露给程序员，而无需公开底层 DRAM 物理细节。`Distributed Shared Memory` 本质上就是按更大作用域暴露的软件管理存储空间。  
   - CUDA Programming Guide: https://docs.nvidia.com/cuda/archive/12.5.1/cuda-c-programming-guide/index.html
3. Triton 当前的 tensor descriptor 和 local memory 抽象，本质上也是先暴露编程所需的逻辑布局与作用域，再由 lowering 和后端去决定具体执行细节，而不是直接暴露物理 bit-level 地址映射。  
   - `make_tensor_descriptor`: https://triton-lang.org/main/python-api/generated/triton.language.make_tensor_descriptor.html  
   - Triton GPU Ops: https://triton-lang.org/main/dialects/TritonGPUOps.html
4. Stratum 这类 Mono3D DRAM 研究也把近内存结构描述为 `chip -> channel -> bank` 的层级，并在系统层面围绕 `channel` 组织处理单元，因此以 `channel` 作为最高层级抽象具有研究合理性。  
   - Stratum 论文信息页: https://experts.illinois.edu/en/publications/stratum-system-hardware-co-design-with-tiered-monolithic-3d-stack/

本文据此作出如下建模选择：

1. `channel` 是程序员可见的最高层级并行单元；
2. `bank/row/col` 不直接暴露给程序员；
3. 更细粒度的落点、冲突和调度细节由后端模型、编译器 cost model 或模拟器决定；
4. 这样既符合现有 GPU 编程模型风格，也避免将研究问题退化成手写地址异或规则。

---

## 3. M3D Scratchpad Programming Model

### 3.1 编程模型定义

`M3D scratchpad` 是一种新的逻辑存储空间，具有如下语义：

1. `scope = cluster`：存储对象在 cluster 范围内可见；
2. `visibility = channel-aware`：数据布局和复用以 `channel` 为上层组织单位；
3. `software-managed`：无透明硬件缓存语义，依赖显式搬运与同步；
4. `explicit-latency`：用户需要通过异步搬运和流水化使用来掩盖其访问延迟；
5. `non-coherent by default`：除非显式同步，否则不假设与其他层级保持透明一致性；
6. `tensor-friendly`：优先支持 tile、descriptor、block layout 这类张量访存模式。

### 3.2 程序员应当感知的对象

程序员不应直接感知地址映射位，而应感知以下五类对象：

1. `allocation`：M3D 空间中的逻辑缓冲区；
2. `descriptor`：张量 shape、stride、block shape 与 `channel` 布局说明；
3. `async copy`：从 `global` 到 `m3d`，以及从 `m3d` 到 `shared` 或寄存器的异步搬运；
4. `barrier/wait`：用于保证跨 warp 或跨 block 的可见性；
5. `pipeline stage`：多阶段预取、双缓冲或 warp specialization 的软件流水线。

### 3.3 访问代价模型

本草案建议将 M3D 访问成本显式建模为：

`shared memory < M3D scratchpad < remote global memory`

并进一步分解为：

1. `m3d_hit_latency`：M3D 命中延迟；
2. `m3d_channel_conflict_penalty`：同一 `channel` 冲突惩罚；
3. `m3d_fill_latency`：从 `global` 填充到 M3D 的代价；
4. `m3d_to_smem_latency`：M3D 到 shared 的搬运延迟；
5. `cluster_barrier_cost`：cluster 级同步代价。

### 3.4 与现有 CUDA/Triton 抽象的关系

该编程模型不是凭空创造，而是对现有抽象的系统化扩展：

1. 类似 CUDA `Distributed Shared Memory`：扩大可见范围与显式同步语义；
2. 类似 `cuda::memcpy_async` / `cp.async`：强调显式搬运和等待；
3. 类似 Triton `local_alloc` / `local_load` / `local_store`：以显式 memory descriptor 访问软件管理存储；
4. 类似 `make_tensor_descriptor`：让用户描述 tensor block，而不是手写地址位逻辑。

相关文档：

1. CUDA Distributed Shared Memory: https://docs.nvidia.com/cuda/archive/12.5.1/cuda-c-programming-guide/index.html
2. PTX `cp.async`: https://docs.nvidia.com/cuda/parallel-thread-execution/index.html#data-movement-and-conversion-instructions-cp-async
3. Hopper warp specialization / async pipeline: https://docs.nvidia.com/cuda/archive/13.0.1/hopper-tuning-guide/index.html
4. Triton GPU Ops: https://triton-lang.org/main/dialects/TritonGPUOps.html

---

## 4. CUDA-like API 草案

### 4.1 设计原则

1. 不修改 CUDA 语言语法；
2. 先以库接口形式提供 M3D 抽象；
3. 用户显式表达搬运、同步和作用域；
4. 将更细粒度的 `channel` 分布与冲突处理交由后端执行。

### 4.2 Host 侧接口

```cpp
enum class M3DScope {
  kCluster,
};

struct M3DLayoutDesc {
  int rank;
  int64_t shape[5];
  int64_t strides[5];
  int64_t block_shape[5];
  int channels;
  bool cluster_resident;
};

template <typename T>
struct M3DSpan {
  T* base;
  size_t bytes;
  M3DLayoutDesc layout;
};

template <typename T>
M3DSpan<T> m3dMallocSpan(T* backing_ptr, size_t bytes, const M3DLayoutDesc& desc);

void m3dSetClusterDim(dim3 cluster_dim);
```

### 4.3 Device 侧接口

```cpp
template <typename T>
__device__ void m3d_async_copy(M3DSpan<T> dst, const T* src, size_t bytes);

__device__ void m3d_wait();

template <typename T>
__device__ T m3d_load(const M3DSpan<T>& src, int64_t linear_idx);

template <typename T>
__device__ void m3d_store(M3DSpan<T>& dst, int64_t linear_idx, T value);

__device__ void m3d_cluster_barrier();
```

### 4.4 语义解释

1. `m3dMallocSpan`：创建 M3D 逻辑对象，不要求真实硬件已有独立地址空间；MVP 可映射到一段预留 `global` backing store。
2. `m3d_async_copy`：表达显式预取语义，MVP 可降成普通 load/store、`cuda::memcpy_async` 或 `cp.async` 风格的近似实现。
3. `m3d_wait`：等待当前拷贝组完成。
4. `m3d_load/store`：通过 M3D 逻辑描述符访问中间层数据。
5. `m3d_cluster_barrier`：保证 cluster 范围内数据可见性。

### 4.5 代表性用法

```cpp
extern "C" __global__ void gemm_m3d_kernel(const half* A,
                                            const half* B,
                                            half* C,
                                            int M,
                                            int N,
                                            int K) {
  cooperative_groups::cluster_group cluster = cooperative_groups::this_cluster();

  __shared__ half smem_tile[128 * 32];

  M3DLayoutDesc desc{/*rank=*/2,
                     /*shape=*/{M, K, 0, 0, 0},
                     /*strides=*/{K, 1, 0, 0, 0},
                     /*block_shape=*/{128, 32, 0, 0, 0},
                     /*channels=*/16,
                     /*cluster_resident=*/true};

  auto a_m3d = m3dMallocSpan((half*)A, sizeof(half) * M * K, desc);

  m3d_async_copy(a_m3d, A, sizeof(half) * 128 * 32);
  m3d_wait();
  m3d_cluster_barrier();

  half x = m3d_load(a_m3d, threadIdx.x);
  smem_tile[threadIdx.x] = x;
}
```

说明：

1. 用户看到的是 scratchpad 风格的接口，而不是新的 PTX 助记符；
2. `channel` 只在 layout descriptor 中作为高层可见维度存在；
3. 更细粒度的下层地址落点不暴露给用户。

---

## 5. Triton/Gluon Lowering Path 草案

### 5.1 设计目标

在 Triton/Gluon 中，M3D 不应以“新增大量指令名”的形式暴露，而应作为：

1. 一种新的 memory space；或
2. 一种新的 tensor descriptor backend；或
3. 一种建立在 `local_alloc + async_copy + descriptor` 之上的复合 lowering 模式。

这与 `Linear Layouts` 的思想一致：用户声明逻辑 tensor 布局，编译器负责映射到目标 memory layout。  
来源：`Linear Layouts: Robust Code Generation of Efficient Tensor Computation Using F2`  
https://arxiv.org/html/2505.23819v1

### 5.2 前端抽象

建议在 Triton 层引入如下逻辑对象：

```python
desc = tl.make_m3d_descriptor(
    base=ptr,
    shape=[M, N],
    strides=[N, 1],
    block_shape=[BM, BN],
    channels=16,
    scope="cluster",
)

token = tl.async_copy_global_to_m3d(desc, [moff, noff])
tl.m3d_wait(token)
tile = tl.load_m3d(desc, [moff, noff])
```

### 5.3 IR 层设计

在 MLIR/TritonGPU 层，建议采用“最少新增语义”的方式：

1. 复用 `MemDescType` 或 `TensorDescType`；
2. 为 descriptor 附加 `m3d`, `cluster`, `channels` 等属性；
3. 复用现有 async copy / wait 机制；
4. 在 lowering pass 中选择具体后端实现。

示意路径如下：

1. 前端 `make_m3d_descriptor`
2. 生成带 `m3d` 属性的 `TensorDescType`
3. `ttg.async_copy_global_to_local` 或 `ttng.async_tma_copy_global_to_local` 的扩展变体承接数据搬运
4. `ttg.local_load/store` 风格 op 访问 M3D-backed memdesc
5. NVIDIA backend 再决定：
   - 真正的模拟器建模路径
   - 或真实 GPU 上的近似映射路径

相关 Triton 文档：

1. `make_tensor_descriptor`: https://triton-lang.org/main/python-api/generated/triton.language.make_tensor_descriptor.html
2. `ttg.local_alloc`, `ttg.local_load`, `ttg.async_copy_global_to_local`: https://triton-lang.org/main/dialects/TritonGPUOps.html
3. `ttng.async_tma_copy_global_to_local`: https://triton-lang.org/main/dialects/TritonNvidiaGPUOps.html

### 5.4 与 Gluon/Linear Layouts 的关系

M3D 的编译抽象不应从“policy name”出发，而应从“layout target space”出发。更具体地说：

1. 逻辑 tensor 坐标仍然由 Gluon/Linear Layouts 处理；
2. 目标空间从传统的 register/lane/warp/block/smem，扩展为包含 `channel-visible` 的 M3D 目标空间；
3. 编译器负责推导 tile 如何按 `channel` 划分与复用；
4. 后端根据目标平台决定其是：
   - 真实 M3D scratchpad 模型；
   - 还是 software-emulated M3D layout。

由此，方案 B 并不是完全推翻方案 A，而是将 A 的 scratchpad 语义进一步提升为 descriptor/layout-first 的编译抽象。

---

## 6. 实现路线：方案 A 的最小落地

### 6.1 研究假设

我们假设底层硬件中存在 cluster-shared 的 Mono3D DRAM scratchpad，但不要求修改真实商用 GPU 的内存控制器实现。MVP 主要在模拟器或 software-emulated 环境中验证以下问题：

1. 程序员显式管理 M3D 是否比单纯依赖 `global/shared` 更有优势；
2. `channel` 感知的张量布局是否能改善并行性与复用；
3. warp specialization 是否能有效隐藏 M3D 访问延迟。

### 6.2 最小实现步骤

1. 在用户接口层提供 `m3dMallocSpan`、`m3d_async_copy`、`m3d_wait`、`m3d_load/store`、`m3d_cluster_barrier`。
2. 在 runtime 中为 M3D 逻辑对象分配一段 backing store，并维护 descriptor 元数据。
3. 在 Accel-Sim/GPGPU-Sim 中新增或复用 `L1.5 scratchpad` 作为 M3D backend。
4. 通过地址区间、sidecar metadata 或 descriptor 元数据将 M3D 访问从普通 global 访问中区分出来。
5. 为 M3D backend 建立以下参数：
   - 容量
   - 每 cluster 的 M3D 数量
   - `channel` 数量
   - 每 `channel` 服务带宽
   - 命中延迟
   - 冲突惩罚
   - 填充延迟

### 6.3 为什么不先修改 CUDA 语法或 PTX

1. 修改 CUDA 语法意味着重写语言前端，工程代价远大于研究收益；
2. 修改 PTX 助记符会把研究问题过早下沉到 ISA 层，不利于保持与 Triton/Gluon 的抽象一致性；
3. 现有公开抽象已足以表达所需语义：`cluster`, `shared`, `memcpy_async`, `tensor descriptor`, `async wait`；
4. 因而更合适的路线是“库接口 + 模拟器建模”或“MLIR op + lowering pass”，而不是先引入新语言关键字。

---

## 7. 论文方法章节草案

### 7.1 方法总览

我们提出 `M3D scratchpad programming model`，将 Monolithic 3D DRAM 暴露为一种 cluster-scoped、channel-visible、software-managed 的显式中间存储层。与传统依赖控制器隐式管理的数据缓存方式不同，该模型要求程序员或编译器显式指定数据驻留、异步搬运和同步关系，从而在不暴露底层物理地址位的前提下，使 3D DRAM 的延迟特征与并行结构进入可编程空间。

### 7.2 编程模型

编程模型包含三个核心对象：

1. `M3D object`：表示驻留于 M3D 的逻辑张量或 tile；
2. `M3D descriptor`：编码 shape、stride、block shape、scope 和 `channel` 元数据；
3. `M3D pipeline`：由 `async copy + wait + barrier` 组成的软件流水线。

与 `shared memory` 类似，M3D 不提供透明一致性，也不自动决定何时装入或替换数据；这些决策由 kernel 作者、运行时或编译器显式控制。

### 7.3 编译与运行时路径

在 CUDA-like 版本中，我们以库接口的方式暴露 M3D 语义，并通过 runtime 为 M3D 对象绑定 backing store 与 descriptor 元数据。在 Triton/Gluon 版本中，我们进一步将该对象提升为 descriptor-first 抽象，使编译器可基于 tensor shape 与 block layout 自动生成搬运与访问代码。

底层执行采用两类路径：

1. 模拟器原生路径：在 Accel-Sim 中将 M3D 访问映射到 cluster-shared scratchpad backend；
2. 软件近似路径：在真实 GPU 上以 `global + shared + async copy` 近似模拟 M3D 的使用方式。

### 7.4 硬件模型

我们将 M3D 建模为位于 `shared memory` 与远端 `global memory` 之间的中间存储层。程序可见的最高层级并行单位为 `channel`。每个 M3D 对象在逻辑上按 `channel` 感知的方式分块；而更细粒度的物理层级由后端模型负责解析，不直接暴露给程序员。

该建模选择的依据是：公开堆叠 DRAM 资料与 Mono3D 研究均首先以 `channel` 组织高层并行性，而 Triton/CUDA 的成熟抽象也倾向于暴露逻辑作用域和布局，而非直接公开物理位级规则。

### 7.5 实验设置

我们建议使用三组实验：

1. `Global/Shared baseline`：无 M3D，仅使用常规 global/shared 路径；
2. `M3D-A`：使用 CUDA-like M3D scratchpad API，由程序员显式管理搬运与同步；
3. `M3D-B`：使用 Triton/Gluon descriptor-backed M3D 抽象，由编译器自动生成部分或全部搬运逻辑。

工作负载应覆盖：

1. GEMM
2. Attention / KV cache
3. MoE expert routing
4. 规则张量核与带轻度不规则访问的对照核

评价指标应至少包括：

1. 总执行周期 / 吞吐
2. M3D 命中率
3. `channel` 冲突率
4. 平均访问延迟与尾延迟
5. async copy 重叠率
6. cluster barrier 开销
7. 每阶段流水线利用率

### 7.6 威胁有效性

1. 若在真实 GPU 上运行，M3D 只能通过现有 memory spaces 近似模拟，因此结论应表述为“software-managed intermediate memory emulation”，而非宣称商用 GPU 已原生支持该层级。
2. 若在模拟器中运行，M3D 的绝对延迟与带宽取决于参数设定，因此应报告敏感性分析而不仅是单点结果。
3. `channel-visible` 是有意保留的高层抽象，其目的在于与现有编程模型对齐；本文不宣称程序员可直接控制更细粒度的物理 DRAM 结构。

---

## 8. 从方案 A 逐步过渡到方案 B

### 8.1 阶段 A0：模拟器原生 scratchpad

目标：在不改 CUDA 语法、不改 Triton 前端的前提下验证 M3D 作为独立中间层的价值。

工作内容：

1. 在模拟器中完成 M3D/L1.5 backend；
2. 通过地址区间或 metadata 区分 M3D 对象；
3. 提供 CUDA-like API；
4. 手工编写 warp specialization kernel。

产出：证明 M3D scratchpad 作为新 memory space 是否值得保留。

### 8.2 阶段 A1：增强为 descriptor-backed API

目标：减少程序员手工管理细节，让 M3D 更接近 tensor 编程模型。

工作内容：

1. 从线性 buffer API 扩展到 `M3DLayoutDesc`；
2. 支持 `shape/stride/block_shape/channels`；
3. runtime 根据 descriptor 选择更优的搬运粒度和同步方式。

产出：为 Triton/Gluon lowering 建立统一数据结构。

### 8.3 阶段 B0：Triton frontend 接入

目标：在 Triton 中引入 `make_m3d_descriptor` 级别的前端接口。

工作内容：

1. 新增前端 API 或 intrinsic；
2. 复用 `make_tensor_descriptor` 和 memdesc 语义；
3. 在 lowering pass 中将 M3D descriptor 展开为 async copy + load/store + barrier。

产出：用户可在 Triton 代码中直接声明 M3D 对象。

### 8.4 阶段 B1：Gluon/Linear Layout 集成

目标：将 M3D 从“用户手写 descriptor”进一步推进到“编译器自动布局”。

工作内容：

1. 将 `channel` 作为 M3D 目标空间的高层维度；
2. 让编译器根据 tensor shape、tile shape、producer/consumer 关系选择 `channel` 可见布局；
3. 让 lowering 自动决定搬运批次、双缓冲深度和 barrier 位置。

产出：形成真正的方案 B，即 descriptor/layout-first 的 M3D 编程模型。

### 8.5 阶段 B2：自动化 cost model

目标：把 A 中程序员承担的时序调优，迁移给编译器和运行时。

工作内容：

1. 建立 M3D latency / bandwidth / channel conflict cost model；
2. 自动选择 tile 形状、pipeline depth、warp role 分工；
3. 在模拟器结果上回标验证 cost model 的准确性。

产出：形成完整的“compiler-guided channel-visible M3D abstraction”。

---

## 9. 建议的论文题目方向

1. `M3D Scratchpad: A Channel-Visible Programming Model for Monolithic 3D DRAM`
2. `From Distributed Shared Memory to M3D Scratchpad: A Compiler-Guided Intermediate Memory Abstraction`
3. `Channel-Visible Tensor Descriptors for Software-Managed Monolithic 3D DRAM`

---

## 10. 本草案的结论

本文建议将 Mono3D DRAM 以 `M3D scratchpad` 的形式暴露给程序员，而不是首先构造新的控制器策略接口。其基本判断是：

1. 若研究目标是建立与 CUDA/Triton/Gluon 风格一致的编程抽象，则 `memory-space-first` 比 `policy-first` 更合理；
2. 若研究目标是降低实现门槛，则方案 A 可以在不改 CUDA 语法、不改 PTX 指令集的前提下落地；
3. 若研究目标是形成更强的编译器创新，则可以以方案 A 为基础，逐步演进到 descriptor/layout-first 的方案 B；
4. `channel` 作为程序可见最高层级，既符合公开堆叠 DRAM 的系统级组织方式，也更适合作为高层编程抽象。

