# M3D Scratchpad Implementation Plan

## 1. 目标

基于 `doc/m3d_scratchpad_programming_model_draft.md`，在当前仓库中实现方案 A 的最小可用版本（MVP），即：

1. 不修改 CUDA 语言语法；
2. 不引入新的 PTX 指令助记符；
3. 在模拟器中把 3D Monolithic DRAM 暴露为一个 `cluster` 作用域、`channel` 可见、软件管理的 scratchpad；
4. 在接口层提供 CUDA-like API 草案与最小原型；
5. 为后续向方案 B（Triton/Gluon descriptor/layout-first）演进预留元数据接口。

---

## 2. 本次实现边界

### 2.1 必做

1. 保留并复用现有 `L1.5 scratchpad` 模型；
2. 将其从“纯隐式 probe/fill”逐步改造成“可被显式 M3D 对象命中/使用”的路径；
3. 增加一套 `M3D descriptor` / `M3D allocation` 的软件元数据定义；
4. 增加实验脚本支持，方便对 M3D-enabled workload 进行系统对比；
5. 增加文档和最小测试。

### 2.2 不做

1. 不改 CUDA 编译器前端；
2. 不改 PTX ISA；
3. 不尝试在真实 NVIDIA GPU 上实现“原生 M3D”硬件支持；
4. 不在本轮实现完整 Triton frontend；
5. 不将 `policy-first` 作为主要接口对外暴露。

---

## 3. 总体阶段

### Phase 0: 基线确认

目标：确认现有 L1.5/M3D 代码路径、实验脚本与文档状态。

任务：

1. 核对 `doc/accelsim_m3d_l15_session_memory.md` 当前状态；
2. 核对 `gpu-simulator/gpgpu-sim` 子仓库是否保持已有 M3D/L1.5 改动；
3. 确认 `util/m3d_experiments/run_m3d_experiments.py` 可继续复用；
4. 确认工作区没有新的异常改动。

验收：

1. 能明确当前 L1.5 的 probe/fill 接入点；
2. 能明确当前实验脚本的 workload 与 config 生成路径；
3. 不误改已有用户未提交内容。

---

### Phase 1: 定义 M3D 软件对象与元数据

目标：引入方案 A 所需的软件抽象，但先不碰 CUDA 语法。

建议新增文件：

1. `doc/m3d_cuda_like_api_draft.md`
2. `util/m3d_experiments/examples/` 下新增 M3D workload / metadata 示例
3. 如需代码骨架，可在根仓库新增：
   - `util/m3d_runtime/README.md`
   - `util/m3d_runtime/m3d_api.h`
   - `util/m3d_runtime/m3d_descriptor.h`

任务：

1. 定义 `M3DLayoutDesc` 数据结构：
   - `rank`
   - `shape[]`
   - `strides[]`
   - `block_shape[]`
   - `channels`
   - `cluster_resident`
2. 定义 `M3DSpan<T>` 或类似逻辑对象；
3. 明确 API 名字：
   - `m3dMallocSpan`
   - `m3d_async_copy`
   - `m3d_wait`
   - `m3d_load`
   - `m3d_store`
   - `m3d_cluster_barrier`
4. 约定 M3D 对象的 backing store 表示方式：
   - 地址区间标记；或
   - sidecar metadata；或
   - launch-time descriptor 文件

推荐选择：

1. 第一轮优先用“地址区间 + metadata 文件”双轨方案；
2. 地址区间用于模拟器分流；
3. metadata 文件用于后续 descriptor/layout-first 演进。

验收：

1. 文档中给出 API 语义；
2. 至少有一个 descriptor 示例；
3. 说明 M3D 对象如何与 trace / workload 绑定。

---

### Phase 2: 在模拟器中增加显式 M3D 对象识别

目标：让模拟器区分“普通 global load/store”与“属于 M3D 对象的访问”。

重点文件：

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc`
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.h`
3. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.cc`
4. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.h`
5. 可能需要：
   - `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc`
   - `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.h`

任务：

1. 增加“地址是否属于 M3D 对象”的判定函数；
2. 为 M3D 对象建立配置项：
   - `-gpgpu_m3d_object_map_file`
   - 或等价命名
3. M3D 对象命中时：
   - load 走显式 M3D/L1.5 scratchpad 路径
   - fill / reservation / bank / channel 统计单独记录
4. 将当前 L1.5 统计扩展为更贴近 M3D scratchpad 的统计字段：
   - `gpgpu_n_m3d_access`
   - `gpgpu_n_m3d_hit`
   - `gpgpu_n_m3d_miss`
   - `gpgpu_n_m3d_channel_conflict`
   - `gpgpu_n_m3d_fill`
5. 明确 M3D 与原 L1/L2/global 路径的关系：
   - M3D 命中则短路后续访问
   - M3D 未命中则继续 global 路径

推荐实现策略：

1. 不要推翻现有 `l15_scratchpad` 类；
2. 先在其基础上增加“M3D object-aware”判定；
3. 将“是否访问 L1.5”从“所有 load 都 probe”逐步收敛到“只对 M3D 对象 probe”。

验收：

1. 可以通过配置文件开启/关闭 M3D object-aware 模式；
2. 非 M3D 地址行为保持不变；
3. M3D 地址访问会反映到新统计项中。

---

### Phase 3: 引入 `channel` 可见建模

目标：让方案 A 从“普通 scratchpad”提升为“channel-visible scratchpad”。

重点文件：

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.h`
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.cc`
3. 相关配置文件：
   - `gpu-simulator/gpgpu-sim/configs/.../gpgpusim.config`

任务：

1. 将当前内部 bank 组织扩展或重解释为：
   - `channels`
   - 每 `channel` 的服务能力
2. 增加配置项：
   - `-gpgpu_m3d_channels`
   - `-gpgpu_m3d_channel_latency`
   - `-gpgpu_m3d_fill_latency`
   - `-gpgpu_m3d_channel_busy_cycles`
3. 新增 `channel` 级别的分配/冲突逻辑；
4. 将统计从 bank 冲突拓展到 `channel` 冲突；
5. 保持更细粒度结构不对程序员可见。

实现建议：

1. 第一轮可以直接把当前 `m_num_banks` 抽象重命名/包装为 `channels`；
2. 不必一次性重写全部内部模型；
3. 先让外部语义和统计以 `channel` 呈现。

验收：

1. `gpgpu-sim-out` 中可看到 `channel` 相关统计；
2. 不同 `channel` 参数设置能造成性能差异；
3. 文档语义与统计口径一致。

---

### Phase 4: 实验脚本与 workload 绑定

目标：让 M3D 实验可批量跑通。

重点文件：

1. `util/m3d_experiments/run_m3d_experiments.py`
2. 新增示例：
   - `util/m3d_experiments/examples/m3d_object_map_example.csv`
   - `util/m3d_experiments/examples/m3d_descriptor_example.json`

任务：

1. 为实验脚本增加 `--m3d-object-map` 参数；
2. 将对象映射文件自动写入生成的 run directory；
3. 将相关 config 自动注入：
   - `-gpgpu_m3d_object_map_file`
   - `-gpgpu_m3d_channels`
4. summary CSV 增加 M3D 统计字段；
5. 为至少一个 workload 生成最小示例。

对象映射文件建议格式：

```csv
# start_addr_hex,end_addr_hex,object_name,channels,scope
0x00000000,0x000fffff,A_tile,16,cluster
0x00100000,0x001fffff,B_tile,16,cluster
```

descriptor 文件建议格式：

```json
{
  "objects": [
    {
      "name": "A_tile",
      "shape": [4096, 4096],
      "strides": [4096, 1],
      "block_shape": [128, 32],
      "channels": 16,
      "scope": "cluster"
    }
  ]
}
```

验收：

1. 能根据 object map 自动生成实验目录；
2. 汇总脚本能提取新增 M3D 统计；
3. 示例文件可直接被用户复制改写。

---

### Phase 5: 文档与最小测试

目标：保证后续 session 可接续开发。

建议新增/更新文件：

1. 更新 `doc/accelsim_m3d_l15_session_memory.md`
2. 更新 `doc/accelsim_m3d_l15_change_explainer.md`
3. 新增 `doc/m3d_object_map_format.md`
4. 新增或更新测试：
   - `util/m3d_experiments/tests/test_run_m3d_experiments.py`

任务：

1. 文档写清楚：
   - M3D object map 格式
   - channel 参数含义
   - 方案 A 的实现边界
2. 增加实验脚本测试：
   - 识别 object map
   - 正确写入 config
   - 正确汇总字段
3. 如可行，增加一个极小的 simulator 侧单元测试或静态构造测试。

验收：

1. `unittest` 至少覆盖脚本参数与输出；
2. 文档可让新 session 直接接手；
3. 关键配置项和统计项均有说明。

---

## 4. 文件级改动建议

### 根仓库

1. `doc/m3d_scratchpad_programming_model_draft.md`
   - 已存在，作为总设计草案
2. `doc/m3d_scratchpad_implementation_plan.md`
   - 当前文档
3. `doc/m3d_cuda_like_api_draft.md`
   - API 专项说明
4. `doc/m3d_object_map_format.md`
   - object map / descriptor 格式说明
5. `util/m3d_experiments/run_m3d_experiments.py`
   - 增加 object map 与 M3D 汇总支持
6. `util/m3d_experiments/tests/test_run_m3d_experiments.py`
   - 增加参数和 summary 测试

### gpgpu-sim 子仓库

1. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.h`
2. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/l15_scratchpad.cc`
3. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.h`
4. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/shader.cc`
5. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.h`
6. `gpu-simulator/gpgpu-sim/src/gpgpu-sim/gpu-sim.cc`
7. 需要时新增：
   - `gpu-simulator/gpgpu-sim/src/gpgpu-sim/m3d_object_map.h`
   - `gpu-simulator/gpgpu-sim/src/gpgpu-sim/m3d_object_map.cc`

推荐新增类：

```cpp
class m3d_object_map {
 public:
  bool enabled() const;
  void load(const char* path);
  bool match(new_addr_type addr) const;
  const m3d_object_desc* lookup(new_addr_type addr) const;
};
```

---

## 5. 配置项建议

建议新增以下配置项：

1. `-gpgpu_m3d_object_map_enable`
2. `-gpgpu_m3d_object_map_file`
3. `-gpgpu_m3d_channels`
4. `-gpgpu_m3d_hit_latency`
5. `-gpgpu_m3d_fill_latency`
6. `-gpgpu_m3d_channel_busy_cycles`
7. `-gpgpu_m3d_scope_mode`

建议的默认值：

1. object map 默认关闭；
2. channels 默认和当前 L1.5 bank 数一致；
3. hit latency 默认复用当前 `gpgpu_l15_latency`；
4. fill latency 默认复用原 global fill 路径并额外加固定成本。

---

## 6. 最小验证矩阵

### 功能验证

1. `M3D off`：行为与当前基线一致；
2. `M3D on + empty object map`：行为接近基线；
3. `M3D on + valid object map`：出现 M3D 统计；
4. 改变 `channels` 参数后：冲突/性能发生变化。

### 性能对比

至少跑三组：

1. `baseline`：无 M3D
2. `m3d-manual`：对象映射到 M3D
3. `m3d-manual + cp.async style workload`：观察 overlap 效应

### 指标

1. `gpu_sim_cycle`
2. `gpu_ipc`
3. `gpgpu_n_m3d_access`
4. `gpgpu_n_m3d_hit`
5. `gpgpu_n_m3d_miss`
6. `gpgpu_n_m3d_channel_conflict`
7. `gpgpu_n_l15_*` 保留作为兼容指标

---

## 7. 风险与规避

1. 风险：现有 L1.5 路径默认对 load 全量 probe，若直接改逻辑可能影响基线。
   - 规避：先加 object-aware 开关，默认关闭。
2. 风险：`channel` 语义与内部 `bank` 实现不完全一致。
   - 规避：第一轮先把 `channel` 作为对外抽象和统计层，不追求一次性重做底层所有细节。
3. 风险：真实 trace 中缺少“这是 M3D 对象”的显式信息。
   - 规避：通过地址区间 map 和 sidecar metadata 显式绑定。
4. 风险：测试环境缺少 `nvcc`，无法完成端到端 CUDA 编译验证。
   - 规避：优先做脚本测试、配置生成测试和模拟器侧静态测试。

---

## 8. 交付顺序建议

严格按下面顺序做：

1. 文档和对象格式先定稿
2. object map 读入与配置接入
3. shader 路径分流
4. l15/M3D 统计扩展
5. experiments 脚本更新
6. 最小测试
7. session memory 更新

不要一开始就做：

1. Triton frontend 改造
2. 新 PTX 助记符
3. 复杂自动布局 cost model

---

## 9. 新 session 推荐提示词

```text
请基于以下文档继续实现方案 A 的 M3D scratchpad MVP：
1. /home/zhanglx/accel-sim-framework/doc/m3d_scratchpad_programming_model_draft.md
2. /home/zhanglx/accel-sim-framework/doc/m3d_scratchpad_implementation_plan.md
3. /home/zhanglx/accel-sim-framework/doc/accelsim_m3d_l15_session_memory.md

要求：
- 不修改 CUDA 语法
- 不引入新的 PTX 指令助记符
- 优先复用现有 L1.5 scratchpad 模型
- 以 object map + channel-visible scratchpad 的方式实现 M3D
- 先完成 object-aware 模拟器分流、配置接入、实验脚本支持和最小测试
- 不要破坏当前已有提交和用户未提交修改
```

---

## 10. 完成定义

本轮工作可视为完成，当且仅当：

1. 有一套可读的 `M3D object map` 格式；
2. 模拟器能识别 M3D 地址对象并走显式路径；
3. 输出中能看到 `channel` 相关统计；
4. 实验脚本能自动生成并汇总相关实验；
5. 文档足够支持下一轮做 Triton/Gluon lowering。
