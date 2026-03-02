# Accel-Sim M3D/L1.5 会话记忆与接力手册

## 1. 这份文档的用途

用于新开窗口后快速恢复上下文，避免重复排查仓库结构、远程、提交状态和已实现范围。

---

## 2. 仓库拓扑（非常关键）

当前工程是“根仓库 + 嵌套子仓库”的形态：

1. 根仓库：`/home/zhanglx/accel-sim-framework`
2. gpgpu-sim 子仓库：`/home/zhanglx/accel-sim-framework/gpu-simulator/gpgpu-sim`
3. gpu-app-collection 子仓库：`/home/zhanglx/accel-sim-framework/util/tuner/gpu-app-collection-partial`

注意：

- `gpu-simulator/gpgpu-sim` 是独立 git 仓库，且被根仓库忽略；  
  所以你在根仓库里看不到 gpgpu-sim 内部代码 diff，这是正常现象。

---

## 3. 已完成提交（用于定位状态）

### 3.1 根仓库

- 分支：`dev`
- 提交：`d774e9f`
- 内容：4090 配置新增 L1.5 与 M3D MC 参数

### 3.2 gpgpu-sim 子仓库

- 分支：`dev`
- 提交：`9f761655`
- 内容：L1.5 模型、MC 映射策略、M3D-aware 调度器、统计扩展

---

## 4. 远程配置（fork 工作流）

### 4.1 根仓库 remotes

- `origin`: `git@github.com:AzureGlacier233/accel-sim-framework-ADA.git`
- `upstream`: `https://github.com/accel-sim/accel-sim-framework.git`

### 4.2 gpgpu-sim 子仓库 remotes

- `origin`: `git@github.com:AzureGlacier233/gpgpu-sim_distribution.git`
- `upstream`: `https://github.com/accel-sim/gpgpu-sim_distribution.git`

### 4.3 gpu-app-collection 子仓库 remotes

- `origin`: `git@github.com:AzureGlacier233/gpu-app-collection.git`
- `upstream`: `https://github.com/accel-sim/gpu-app-collection.git`

---

## 5. 当前工作区状态（接力时先看）

1. 根仓库有一个已存在修改：
   - `util/tuner/gpu-app-collection-partial`（gitlink 状态变更）
2. gpgpu-sim 子仓库有未跟踪目录（此前未纳入提交）：
   - `configs/tested-cfgs/NVIDIA_GeForce_RTX_4090/`
   - `configs/tested-cfgs/SM89_RTX4090/`
   - `tested-cfgs/`
3. 以上状态是已知状态，不是本次实现必须清理的阻塞项。

---

## 6. 已实现范围与未实现范围（快速判断）

### 已实现

1. cluster-shared L1.5 scratchpad（load probe + fill + stats）
2. L1.5 三种策略映射
3. MC 级映射策略（含 region table）
4. M3D-aware FRFCFS 调度评分分支
5. 对应配置项接入与日志打印

### 未实现

1. 自动化实验驱动脚本（T7/T8）
2. Ramulator backend 抽象与接入（T9/T10）
3. 完整编译/回归验证（环境缺失 `nvcc`）

---

## 7. 新窗口开工检查清单

```bash
# 1) 根仓库状态
git -C /home/zhanglx/accel-sim-framework status --short
git -C /home/zhanglx/accel-sim-framework log --oneline -n 3

# 2) gpgpu-sim 子仓库状态
git -C /home/zhanglx/accel-sim-framework/gpu-simulator/gpgpu-sim status --short
git -C /home/zhanglx/accel-sim-framework/gpu-simulator/gpgpu-sim log --oneline -n 3

# 3) 核对关键提交内容
git -C /home/zhanglx/accel-sim-framework show --name-status --oneline d774e9f
git -C /home/zhanglx/accel-sim-framework/gpu-simulator/gpgpu-sim show --name-status --oneline 9f761655
```

---

## 8. 新窗口可直接粘贴的接力提示词

```text
请基于 /home/zhanglx/accel-sim-framework/doc/accelsim_m3d_l15_change_explainer.md 和
/home/zhanglx/accel-sim-framework/doc/accelsim_m3d_l15_session_memory.md 继续工作。
先检查根仓库与 gpgpu-sim 子仓库状态，再在不破坏现有提交 d774e9f / 9f761655 的前提下推进下一步。
```

