# M3D/L1.5 Experiment Driver

该目录实现 `doc/accelsim_m3d_l15_tasklist.md` 中 T7/T8 所需的最小实验驱动：

1. 生成 cluster sweep + policy sweep 的实验目录；
2. 为每个实验自动写入覆盖参数后的 `gpgpusim.config`；
3. 可选直接执行仿真；
4. 解析 `gpgpu-sim-out*.txt` 并汇总为 `summary.csv`。

## 1. 快速使用

```bash
python3 util/m3d_experiments/run_m3d_experiments.py \
  --base-config gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config \
  --run-root sim_run_m3d \
  --workload ldglobal:/abs/path/to/ldglobal_trace_dir \
  --workload cpasync:/abs/path/to/cpasync_trace_dir
```

说明：

1. 不加 `--execute` 时只生成实验目录与 `run.sh`；
2. 加 `--execute` 会顺序执行每个 case；
3. `--resume` 可跳过已有 `gpgpu-sim-out*.txt` 的 case。

## 2. 默认实验矩阵

1. cluster：`128x1,64x2,32x4,16x8`
2. policy：`row_local,bank_balanced,hybrid`
3. baseline：`l15=off + frfcfs`
4. experimental：`l15=on + m3d_aware_frfcfs`

可通过参数覆盖：

1. `--cluster-shapes`
2. `--policies`
3. `--schedulers`
4. `--baseline-scheduler`

## 3. REGION_TABLE 模式

如果要测试 `-gpgpu_m3d_mc_map_mode 3`，可传入 CSV：

```bash
python3 util/m3d_experiments/run_m3d_experiments.py \
  ... \
  --region-policy-table util/m3d_experiments/examples/m3d_region_policy_example.csv
```

CSV 示例见 `examples/m3d_region_policy_example.csv`，字段为：

1. `start_addr_hex`
2. `end_addr_hex`
3. `policy_id`

## 4. 输出内容

每个 case 目录包含：

1. `gpgpusim.config`（已覆写）
2. `traces -> workload trace dir`（软链接）
3. `run.sh`
4. `metadata.json`
5. `gpgpu-sim-out*.txt`（执行后）

汇总 CSV 默认输出到 `sim_run_m3d/summary.csv`，可通过 `--summary-csv` 覆盖。
