#!/usr/bin/env python3

import pathlib
import unittest

from util.m3d_experiments.run_m3d_experiments import (
    Workload,
    apply_config_overrides,
    build_experiment_cases,
    parse_cluster_shapes,
    parse_policy_ids,
    parse_scheduler_ids,
    parse_sim_output_stats,
)


class RunM3DExperimentsTest(unittest.TestCase):
    def test_apply_config_overrides(self) -> None:
        src = (
            "-gpgpu_n_clusters 128\n"
            "-gpgpu_l15_enable 0\n"
            "# comment\n"
            "-gpgpu_dram_scheduler 1\n"
        )
        out = apply_config_overrides(
            src,
            {
                "-gpgpu_n_clusters": "64",
                "-gpgpu_l15_enable": "1",
                "-gpgpu_m3d_mc_map_enable": "1",
            },
        )
        self.assertIn("-gpgpu_n_clusters 64\n", out)
        self.assertIn("-gpgpu_l15_enable 1\n", out)
        self.assertIn("-gpgpu_m3d_mc_map_enable 1\n", out)

    def test_parse_stats(self) -> None:
        text = (
            "gpu_sim_cycle = 12345\n"
            "gpu_tot_sim_cycle = 98765\n"
            "gpgpu_n_l15_access = 100\n"
            "gpgpu_n_l15_hit = 90\n"
            "gpgpu_l15_hit_rate = 0.900000\n"
            "m3d_policy_use: 1 2 3 4\n"
            "m3d_policy_row_hits: 5 6 7 8\n"
            "m3d_policy_bank_conflicts: 9 10 11 12\n"
        )
        got = parse_sim_output_stats(text)
        self.assertEqual(got["gpu_sim_cycle"], "12345")
        self.assertEqual(got["gpu_tot_sim_cycle"], "98765")
        self.assertEqual(got["gpgpu_n_l15_access"], "100")
        self.assertEqual(got["gpgpu_n_l15_hit"], "90")
        self.assertEqual(got["gpgpu_l15_hit_rate"], "0.900000")
        self.assertEqual(got["m3d_policy_use_0"], "1")
        self.assertEqual(got["m3d_policy_use_3"], "4")
        self.assertEqual(got["m3d_policy_row_hits_2"], "7")
        self.assertEqual(got["m3d_policy_bank_conflicts_1"], "10")

    def test_matrix_build_count(self) -> None:
        workloads = [Workload(name="w0", trace_dir=pathlib.Path("/tmp"))]
        cluster_shapes = parse_cluster_shapes("2x4,1x8")
        policies = parse_policy_ids("row_local,bank_balanced,hybrid")
        schedulers = parse_scheduler_ids("m3d_aware_frfcfs")
        cases = build_experiment_cases(
            workloads=workloads,
            cluster_shapes=cluster_shapes,
            policy_ids=policies,
            scheduler_ids=schedulers,
            baseline_scheduler_id=1,
            use_region_table=False,
            policy_table_file="none",
        )
        self.assertEqual(len(cases), 8)
        num_baseline = sum(1 for c in cases if c.l15_enable == 0)
        self.assertEqual(num_baseline, 2)
        num_enabled = sum(1 for c in cases if c.l15_enable == 1)
        self.assertEqual(num_enabled, 6)

    def test_region_table_mode_override(self) -> None:
        workloads = [Workload(name="w0", trace_dir=pathlib.Path("/tmp"))]
        cluster_shapes = parse_cluster_shapes("2x4")
        policies = parse_policy_ids("row_local,bank_balanced")
        schedulers = parse_scheduler_ids("m3d_aware_frfcfs")
        cases = build_experiment_cases(
            workloads=workloads,
            cluster_shapes=cluster_shapes,
            policy_ids=policies,
            scheduler_ids=schedulers,
            baseline_scheduler_id=1,
            use_region_table=True,
            policy_table_file="/tmp/policy.csv",
        )
        baseline = [c for c in cases if c.l15_enable == 0][0]
        self.assertEqual(baseline.m3d_map_mode, 0)
        enabled = [c for c in cases if c.l15_enable == 1]
        self.assertTrue(enabled)
        self.assertTrue(all(c.m3d_map_mode == 3 for c in enabled))
        self.assertTrue(all(c.policy_table_file == "/tmp/policy.csv" for c in enabled))


if __name__ == "__main__":
    unittest.main()
