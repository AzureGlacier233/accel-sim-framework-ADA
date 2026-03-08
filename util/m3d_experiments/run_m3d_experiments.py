#!/usr/bin/env python3

"""Generate and optionally run M3D/L1.5 experiment matrices for Accel-Sim."""

import argparse
import csv
import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


POLICY_NAME_TO_ID = {
    "row_local": 0,
    "bank_balanced": 1,
    "hybrid": 2,
}
POLICY_ID_TO_NAME = {v: k for k, v in POLICY_NAME_TO_ID.items()}

SCHED_NAME_TO_ID = {
    "frfcfs": 1,
    "m3d_aware_frfcfs": 2,
}
SCHED_ID_TO_NAME = {v: k for k, v in SCHED_NAME_TO_ID.items()}

DEFAULT_CLUSTER_SHAPES = "128x1,64x2,32x4,16x8"
DEFAULT_POLICIES = "row_local,bank_balanced,hybrid"


@dataclasses.dataclass(frozen=True)
class Workload:
    name: str
    trace_dir: pathlib.Path


@dataclasses.dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    workload_name: str
    trace_dir: pathlib.Path
    clusters: int
    cores_per_cluster: int
    l15_enable: int
    l15_policy_mode: int
    m3d_map_enable: int
    m3d_map_mode: int
    dram_scheduler: int
    policy_table_file: str

    def overrides(self) -> Dict[str, str]:
        return {
            "-gpgpu_n_clusters": str(self.clusters),
            "-gpgpu_n_cores_per_cluster": str(self.cores_per_cluster),
            "-gpgpu_l15_enable": str(self.l15_enable),
            "-gpgpu_l15_policy_mode": str(self.l15_policy_mode),
            "-gpgpu_m3d_mc_map_enable": str(self.m3d_map_enable),
            "-gpgpu_m3d_mc_map_mode": str(self.m3d_map_mode),
            "-gpgpu_m3d_mc_policy_table_file": self.policy_table_file,
            "-gpgpu_dram_scheduler": str(self.dram_scheduler),
        }


def parse_workload_spec(spec: str) -> Workload:
    if ":" not in spec:
        raise ValueError(
            f"Invalid --workload '{spec}', expected format name:/abs/path/to/trace_dir"
        )
    name, trace = spec.split(":", 1)
    name = name.strip()
    if not name:
        raise ValueError(f"Invalid --workload '{spec}', name cannot be empty")
    trace_path = pathlib.Path(trace).expanduser().resolve()
    return Workload(name=name, trace_dir=trace_path)


def parse_cluster_shapes(spec: str) -> List[Tuple[int, int]]:
    shapes: List[Tuple[int, int]] = []
    for raw in spec.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if "x" not in token:
            raise ValueError(
                f"Invalid cluster shape '{raw}', expected format <clusters>x<cores>"
            )
        c0, c1 = token.split("x", 1)
        clusters = int(c0)
        cores = int(c1)
        if clusters <= 0 or cores <= 0:
            raise ValueError(f"Invalid cluster shape '{raw}', values must be > 0")
        shapes.append((clusters, cores))
    if not shapes:
        raise ValueError("No valid cluster shape is provided")
    return shapes


def parse_policy_ids(spec: str) -> List[int]:
    ret: List[int] = []
    for raw in spec.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token not in POLICY_NAME_TO_ID:
            supported = ",".join(sorted(POLICY_NAME_TO_ID.keys()))
            raise ValueError(f"Unknown policy '{token}', supported: {supported}")
        ret.append(POLICY_NAME_TO_ID[token])
    if not ret:
        raise ValueError("No policy is selected")
    return ret


def parse_scheduler_ids(spec: str) -> List[int]:
    ret: List[int] = []
    for raw in spec.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token not in SCHED_NAME_TO_ID:
            supported = ",".join(sorted(SCHED_NAME_TO_ID.keys()))
            raise ValueError(f"Unknown scheduler '{token}', supported: {supported}")
        ret.append(SCHED_NAME_TO_ID[token])
    if not ret:
        raise ValueError("No scheduler is selected")
    return ret


def apply_config_overrides(config_text: str, overrides: Dict[str, str]) -> str:
    lines = config_text.splitlines()
    key_to_idx: Dict[str, int] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        key = stripped.split(None, 1)[0]
        key_to_idx[key] = idx

    for key, value in overrides.items():
        newline = f"{key} {value}"
        if key in key_to_idx:
            lines[key_to_idx[key]] = newline
        else:
            lines.append(newline)

    return "\n".join(lines) + "\n"


def build_case_id(
    workload_name: str,
    clusters: int,
    cores_per_cluster: int,
    l15_enable: int,
    policy_mode: int,
    scheduler: int,
    m3d_map_mode: int,
) -> str:
    policy = POLICY_ID_TO_NAME.get(policy_mode, f"policy{policy_mode}")
    sched = SCHED_ID_TO_NAME.get(scheduler, f"sched{scheduler}")
    return (
        f"{workload_name}"
        f"__c{clusters}x{cores_per_cluster}"
        f"__l15{l15_enable}"
        f"__{policy}"
        f"__map{m3d_map_mode}"
        f"__{sched}"
    )


def build_experiment_cases(
    workloads: Sequence[Workload],
    cluster_shapes: Sequence[Tuple[int, int]],
    policy_ids: Sequence[int],
    scheduler_ids: Sequence[int],
    baseline_scheduler_id: int,
    use_region_table: bool,
    policy_table_file: str,
) -> List[ExperimentCase]:
    cases: List[ExperimentCase] = []
    for workload in workloads:
        for clusters, cores in cluster_shapes:
            baseline_map_mode = 0
            baseline_case = ExperimentCase(
                case_id=build_case_id(
                    workload.name,
                    clusters,
                    cores,
                    l15_enable=0,
                    policy_mode=0,
                    scheduler=baseline_scheduler_id,
                    m3d_map_mode=baseline_map_mode,
                ),
                workload_name=workload.name,
                trace_dir=workload.trace_dir,
                clusters=clusters,
                cores_per_cluster=cores,
                l15_enable=0,
                l15_policy_mode=0,
                m3d_map_enable=0,
                m3d_map_mode=baseline_map_mode,
                dram_scheduler=baseline_scheduler_id,
                policy_table_file="none",
            )
            cases.append(baseline_case)

            for policy_id in policy_ids:
                map_mode = 3 if use_region_table else policy_id
                for scheduler in scheduler_ids:
                    cases.append(
                        ExperimentCase(
                            case_id=build_case_id(
                                workload.name,
                                clusters,
                                cores,
                                l15_enable=1,
                                policy_mode=policy_id,
                                scheduler=scheduler,
                                m3d_map_mode=map_mode,
                            ),
                            workload_name=workload.name,
                            trace_dir=workload.trace_dir,
                            clusters=clusters,
                            cores_per_cluster=cores,
                            l15_enable=1,
                            l15_policy_mode=policy_id,
                            m3d_map_enable=1,
                            m3d_map_mode=map_mode,
                            dram_scheduler=scheduler,
                            policy_table_file=policy_table_file,
                        )
                    )
    return cases


def ensure_trace_symlink(run_dir: pathlib.Path, trace_dir: pathlib.Path) -> None:
    link = run_dir / "traces"
    if link.exists() or link.is_symlink():
        if link.is_symlink() and os.path.realpath(link) == str(trace_dir):
            return
        if link.is_dir() and not link.is_symlink():
            raise RuntimeError(
                f"{link} already exists as a directory, cannot replace with symlink"
            )
        link.unlink()
    link.symlink_to(trace_dir)


def write_run_script(run_dir: pathlib.Path, sim_bin: str) -> None:
    script = run_dir / "run.sh"
    content = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'SIM_BIN="${{SIM_BIN:-{sim_bin}}}"\n'
        'OUT="${1:-gpgpu-sim-out.txt}"\n'
        '"${SIM_BIN}" -config ./gpgpusim.config -trace ./traces/kernelslist.g '
        '| tee "${OUT}"\n'
    )
    script.write_text(content)
    script.chmod(0o744)


def parse_scalar_stat(text: str, key: str) -> Optional[str]:
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def parse_vector_stat(text: str, key: str, expected_len: int) -> List[Optional[str]]:
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return [None] * expected_len
    parts = match.group(1).strip().split()
    out: List[Optional[str]] = [None] * expected_len
    for idx in range(min(expected_len, len(parts))):
        out[idx] = parts[idx]
    return out


def parse_sim_output_stats(text: str) -> Dict[str, Optional[str]]:
    ret: Dict[str, Optional[str]] = {}
    scalar_keys = [
        "gpu_sim_cycle",
        "gpu_tot_sim_cycle",
        "gpu_ipc",
        "gpgpu_n_l15_access",
        "gpgpu_n_l15_hit",
        "gpgpu_n_l15_miss",
        "gpgpu_n_l15_reservation_fail",
        "gpgpu_n_l15_bank_conflict",
        "gpgpu_n_l15_hit_latency_cycles",
        "gpgpu_l15_hit_rate",
    ]
    for key in scalar_keys:
        ret[key] = parse_scalar_stat(text, key)

    for prefix in [
        "m3d_policy_use",
        "m3d_policy_row_hits",
        "m3d_policy_bank_conflicts",
    ]:
        vals = parse_vector_stat(text, prefix, expected_len=4)
        for idx, value in enumerate(vals):
            ret[f"{prefix}_{idx}"] = value
    return ret


def find_latest_output_file(run_dir: pathlib.Path) -> Optional[pathlib.Path]:
    cands = sorted(run_dir.glob("gpgpu-sim-out*.txt"), key=lambda p: p.stat().st_mtime)
    if not cands:
        return None
    return cands[-1]


def prepare_case(
    case: ExperimentCase,
    base_config_text: str,
    run_root: pathlib.Path,
    sim_bin: str,
) -> pathlib.Path:
    run_dir = run_root / case.workload_name / case.case_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ensure_trace_symlink(run_dir, case.trace_dir)
    cfg = apply_config_overrides(base_config_text, case.overrides())
    (run_dir / "gpgpusim.config").write_text(cfg)
    write_run_script(run_dir, sim_bin)

    metadata = dataclasses.asdict(case)
    metadata["trace_dir"] = str(case.trace_dir)
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))
    return run_dir


def execute_case(run_dir: pathlib.Path, sim_bin: str) -> Tuple[int, pathlib.Path]:
    env = os.environ.copy()
    env["SIM_BIN"] = sim_bin
    out_file = run_dir / "gpgpu-sim-out.txt"
    proc = subprocess.run(
        ["bash", "./run.sh", out_file.name],
        cwd=str(run_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return proc.returncode, out_file


def summary_fieldnames() -> List[str]:
    base = [
        "workload",
        "case_id",
        "run_dir",
        "status",
        "output_file",
        "clusters",
        "cores_per_cluster",
        "l15_enable",
        "l15_policy_mode",
        "l15_policy_name",
        "m3d_map_enable",
        "m3d_map_mode",
        "dram_scheduler",
        "dram_scheduler_name",
    ]
    stats = [
        "gpu_sim_cycle",
        "gpu_tot_sim_cycle",
        "gpu_ipc",
        "gpgpu_n_l15_access",
        "gpgpu_n_l15_hit",
        "gpgpu_n_l15_miss",
        "gpgpu_n_l15_reservation_fail",
        "gpgpu_n_l15_bank_conflict",
        "gpgpu_n_l15_hit_latency_cycles",
        "gpgpu_l15_hit_rate",
    ]
    for prefix in [
        "m3d_policy_use",
        "m3d_policy_row_hits",
        "m3d_policy_bank_conflicts",
    ]:
        for idx in range(4):
            stats.append(f"{prefix}_{idx}")
    return base + stats


def collect_case_summary(
    case: ExperimentCase,
    run_dir: pathlib.Path,
    status: str,
    output_file: Optional[pathlib.Path],
) -> Dict[str, str]:
    row: Dict[str, str] = {
        "workload": case.workload_name,
        "case_id": case.case_id,
        "run_dir": str(run_dir),
        "status": status,
        "output_file": str(output_file) if output_file else "",
        "clusters": str(case.clusters),
        "cores_per_cluster": str(case.cores_per_cluster),
        "l15_enable": str(case.l15_enable),
        "l15_policy_mode": str(case.l15_policy_mode),
        "l15_policy_name": POLICY_ID_TO_NAME.get(case.l15_policy_mode, "unknown"),
        "m3d_map_enable": str(case.m3d_map_enable),
        "m3d_map_mode": str(case.m3d_map_mode),
        "dram_scheduler": str(case.dram_scheduler),
        "dram_scheduler_name": SCHED_ID_TO_NAME.get(case.dram_scheduler, "unknown"),
    }
    for field in summary_fieldnames():
        row.setdefault(field, "")

    if not output_file or not output_file.is_file():
        return row

    stats = parse_sim_output_stats(output_file.read_text(errors="ignore"))
    for key, value in stats.items():
        if value is not None:
            row[key] = value
    return row


def write_summary_csv(rows: Iterable[Dict[str, str]], path: pathlib.Path) -> None:
    fields = summary_fieldnames()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and run M3D-aware mapping experiment matrix."
    )
    parser.add_argument(
        "--base-config",
        default="gpu-simulator/configs/tested-cfgs/SM89_RTX4090/gpgpusim.config",
        help="Base gpgpusim.config used for override generation.",
    )
    parser.add_argument(
        "--run-root",
        default="sim_run_m3d",
        help="Output run root folder for generated experiments.",
    )
    parser.add_argument(
        "--workload",
        action="append",
        default=[],
        help="Workload in format name:/abs/path/to/trace_dir. Repeat for multiple.",
    )
    parser.add_argument(
        "--cluster-shapes",
        default=DEFAULT_CLUSTER_SHAPES,
        help="Comma-separated shape list: 128x1,64x2,32x4,16x8",
    )
    parser.add_argument(
        "--policies",
        default=DEFAULT_POLICIES,
        help="Comma-separated policies: row_local,bank_balanced,hybrid",
    )
    parser.add_argument(
        "--schedulers",
        default="m3d_aware_frfcfs",
        help="Comma-separated schedulers: frfcfs,m3d_aware_frfcfs",
    )
    parser.add_argument(
        "--baseline-scheduler",
        default="frfcfs",
        choices=sorted(SCHED_NAME_TO_ID.keys()),
        help="Scheduler used by l15-off baseline runs.",
    )
    parser.add_argument(
        "--region-policy-table",
        default="",
        help="Optional CSV file. If set, MC mapping mode uses REGION_TABLE (mode 3).",
    )
    parser.add_argument(
        "--sim-bin",
        default="accel-sim.out",
        help="Simulator binary path used in run.sh and --execute.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute all generated runs immediately.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="When used with --execute, skip runs that already have gpgpu-sim-out*.txt.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue execution even if one run returns non-zero.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=0,
        help="Only generate/execute the first N cases. 0 means all.",
    )
    parser.add_argument(
        "--summary-csv",
        default="sim_run_m3d/summary.csv",
        help="Path to output summary CSV.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    base_config = pathlib.Path(args.base_config).expanduser().resolve()
    if not base_config.is_file():
        print(f"Base config not found: {base_config}", file=sys.stderr)
        return 2

    if not args.workload:
        print(
            "At least one --workload is required, e.g. "
            "--workload ldglobal:/path/to/trace_dir",
            file=sys.stderr,
        )
        return 2

    workloads: List[Workload] = []
    for spec in args.workload:
        workload = parse_workload_spec(spec)
        if not workload.trace_dir.is_dir():
            raise FileNotFoundError(f"Trace directory not found: {workload.trace_dir}")
        if not (workload.trace_dir / "kernelslist.g").is_file():
            raise FileNotFoundError(
                f"Missing kernelslist.g under trace dir: {workload.trace_dir}"
            )
        workloads.append(workload)

    cluster_shapes = parse_cluster_shapes(args.cluster_shapes)
    policy_ids = parse_policy_ids(args.policies)
    scheduler_ids = parse_scheduler_ids(args.schedulers)
    baseline_scheduler_id = SCHED_NAME_TO_ID[args.baseline_scheduler]

    use_region_table = bool(args.region_policy_table)
    policy_table_file = "none"
    if use_region_table:
        region_path = pathlib.Path(args.region_policy_table).expanduser().resolve()
        if not region_path.is_file():
            raise FileNotFoundError(f"Region policy table file not found: {region_path}")
        policy_table_file = str(region_path)

    cases = build_experiment_cases(
        workloads=workloads,
        cluster_shapes=cluster_shapes,
        policy_ids=policy_ids,
        scheduler_ids=scheduler_ids,
        baseline_scheduler_id=baseline_scheduler_id,
        use_region_table=use_region_table,
        policy_table_file=policy_table_file,
    )

    if args.max_runs > 0:
        cases = cases[: args.max_runs]

    run_root = pathlib.Path(args.run_root).expanduser().resolve()
    base_text = base_config.read_text()
    summary_rows: List[Dict[str, str]] = []

    for case in cases:
        run_dir = prepare_case(case, base_text, run_root, args.sim_bin)
        status = "generated"
        output_file = find_latest_output_file(run_dir)

        if args.execute:
            if args.resume and output_file:
                status = "skipped_existing_output"
            else:
                rc, out = execute_case(run_dir, args.sim_bin)
                output_file = out
                if rc == 0:
                    status = "completed"
                else:
                    status = f"failed_rc_{rc}"
                    if not args.keep_going:
                        summary_rows.append(
                            collect_case_summary(case, run_dir, status, output_file)
                        )
                        write_summary_csv(
                            summary_rows,
                            pathlib.Path(args.summary_csv).expanduser().resolve(),
                        )
                        print(
                            f"Run failed at {case.case_id} with return code {rc}",
                            file=sys.stderr,
                        )
                        return rc

        summary_rows.append(collect_case_summary(case, run_dir, status, output_file))

    summary_csv = pathlib.Path(args.summary_csv).expanduser().resolve()
    write_summary_csv(summary_rows, summary_csv)

    print(f"Generated {len(cases)} experiment cases under {run_root}")
    print(f"Summary CSV: {summary_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
