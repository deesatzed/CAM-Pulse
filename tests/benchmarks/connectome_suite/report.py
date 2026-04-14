from __future__ import annotations

from pathlib import Path
import json

from tests.benchmarks.connectome_suite.ablation import run_planning_ablation
from tests.benchmarks.connectome_suite.connectome_recipe_ablation import run_connectome_recipe_ablation
from tests.benchmarks.connectome_suite.full_suite import FULL_CONNECTOME_SUITE
from tests.benchmarks.connectome_suite.harness import run_connectome_suite, run_pilot_connectome_suite
from tests.benchmarks.connectome_suite.live_run_harness import run_live_reviewed_benchmark
from tests.benchmarks.connectome_suite.seeded_failures import SEEDED_RETROGRADE_CASES


async def build_connectome_report_data() -> dict[str, object]:
    pilot = run_pilot_connectome_suite()
    full = run_connectome_suite(FULL_CONNECTOME_SUITE)
    planning_ablation = run_planning_ablation()
    recipe_ablation = await run_connectome_recipe_ablation()
    live_run = run_live_reviewed_benchmark()
    seeded_results = [case["payload"]() for case in SEEDED_RETROGRADE_CASES]
    avg_seeded_confidence = sum(result["confidence"] for result in seeded_results) / max(1, len(seeded_results))
    top_kind_counts: dict[str, int] = {}
    root_summary_counts: dict[str, int] = {}
    recommended_action_counts: dict[str, int] = {}
    dominant_cluster_counts: dict[str, int] = {}
    confidence_band_counts: dict[str, int] = {}
    calibration_counts: dict[str, int] = {}
    stability_counts: dict[str, int] = {}
    for result in seeded_results:
        if not result["cause_chain"]:
            continue
        kind = result["cause_chain"][0]["kind"]
        top_kind_counts[kind] = top_kind_counts.get(kind, 0) + 1
        primary_kind = str(result.get("root_cause_summary", {}).get("primary_kind") or "")
        if primary_kind:
            root_summary_counts[primary_kind] = root_summary_counts.get(primary_kind, 0) + 1
        recommended_action = str(result.get("root_cause_summary", {}).get("recommended_action") or "")
        if recommended_action:
            recommended_action_counts[recommended_action] = recommended_action_counts.get(recommended_action, 0) + 1
        dominant_cluster = str(result.get("root_cause_summary", {}).get("dominant_cluster") or "")
        if dominant_cluster:
            dominant_cluster_counts[dominant_cluster] = dominant_cluster_counts.get(dominant_cluster, 0) + 1
        confidence_band = str(result.get("root_cause_summary", {}).get("confidence_band") or "")
        if confidence_band:
            confidence_band_counts[confidence_band] = confidence_band_counts.get(confidence_band, 0) + 1
        calibration = str(result.get("root_cause_summary", {}).get("calibration") or "")
        if calibration:
            calibration_counts[calibration] = calibration_counts.get(calibration, 0) + 1
        stability = str(result.get("root_cause_summary", {}).get("stability") or "")
        if stability:
            stability_counts[stability] = stability_counts.get(stability, 0) + 1

    return {
        "pilot": pilot["summary"],
        "full": full["summary"],
        "planning_ablation": planning_ablation["uplift"],
        "recipe_ablation": recipe_ablation,
        "live_run": live_run,
        "seeded_retrograde": {
            "case_count": len(seeded_results),
            "average_confidence": avg_seeded_confidence,
            "top_kind_counts": top_kind_counts,
            "root_summary_counts": root_summary_counts,
            "recommended_action_counts": recommended_action_counts,
            "dominant_cluster_counts": dominant_cluster_counts,
            "confidence_band_counts": confidence_band_counts,
            "calibration_counts": calibration_counts,
            "stability_counts": stability_counts,
        },
        "local_security_lane": {
            "semgrep_default_path": "Docker runner",
            "codeql_default_path": "deferred/advanced",
        },
    }


async def build_connectome_report() -> str:
    data = await build_connectome_report_data()
    pilot = data["pilot"]
    full = data["full"]
    planning_ablation = data["planning_ablation"]
    recipe_ablation = data["recipe_ablation"]
    live_run = data["live_run"]
    seeded_retrograde = data["seeded_retrograde"]

    lines = [
        "# CAM-SEQ Connectome Benchmark Report",
        "",
        "## Pilot Suite",
        f"- tasks: {pilot['task_count']}",
        f"- archetype accuracy: {pilot['archetype_accuracy']:.2f}",
        f"- slot precision: {pilot['slot_precision']:.2f}",
        f"- slot recall: {pilot['slot_recall']:.2f}",
        f"- critical-slot recall: {pilot['critical_slot_recall']:.2f}",
        "",
        "## Full Suite",
        f"- tasks: {full['task_count']}",
        f"- archetype accuracy: {full['archetype_accuracy']:.2f}",
        f"- slot precision: {full['slot_precision']:.2f}",
        f"- slot recall: {full['slot_recall']:.2f}",
        f"- critical-slot recall: {full['critical_slot_recall']:.2f}",
        "",
        "## Planning Ablation",
        f"- archetype uplift: {planning_ablation['archetype_accuracy']:.2f}",
        f"- slot precision uplift: {planning_ablation['slot_precision']:.2f}",
        f"- slot recall uplift: {planning_ablation['slot_recall']:.2f}",
        f"- critical-slot recall uplift: {planning_ablation['critical_slot_recall']:.2f}",
        "",
        "## Connectome + Recipe Ablation",
        f"- baseline selected: {recipe_ablation['baseline_selected']}",
        f"- learned selected: {recipe_ablation['learned_selected']}",
        f"- recipe selected: {recipe_ablation['recipe_selected']}",
        f"- recipe active: {recipe_ablation['recipe_active']}",
        f"- recipe sample size: {recipe_ablation['recipe_sample_size']}",
        f"- recipe confidence basis: {', '.join(recipe_ablation['recipe_confidence_basis'])}",
        "",
        "## Live Reviewed-Run Harness",
        f"- run count: {live_run['run_count']}",
        f"- completed runs: {live_run['completed_runs']}",
        f"- connectomes: {live_run['connectome_count']}",
        f"- active recipes: {live_run['active_recipe_count']}",
        f"- fourth packet confidence basis: {', '.join(live_run['fourth_packet_confidence_basis'])}",
        f"- workspace mutations: {live_run['workspace_mutation_count']}",
        f"- final landing count: {live_run['final_landing_count']}",
        "",
        "## Seeded Retrograde Cases",
        f"- case count: {seeded_retrograde['case_count']}",
        f"- average confidence: {seeded_retrograde['average_confidence']:.2f}",
        f"- top cause kinds: {', '.join(sorted(seeded_retrograde['top_kind_counts'].keys()))}",
        f"- top cause distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['top_kind_counts'].items()))}",
        f"- root summary distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['root_summary_counts'].items()))}",
        f"- recommended action distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['recommended_action_counts'].items()))}",
        f"- dominant cluster distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['dominant_cluster_counts'].items()))}",
        f"- confidence band distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['confidence_band_counts'].items()))}",
        f"- calibration distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['calibration_counts'].items()))}",
        f"- stability distribution: {', '.join(f'{k}:{v}' for k, v in sorted(seeded_retrograde['stability_counts'].items()))}",
        "",
        "## Local Security Lane",
        "- Semgrep default path: Docker runner",
        "- CodeQL default path: deferred/advanced",
        "",
    ]
    return "\n".join(lines)


async def write_connectome_report(path: str | Path) -> Path:
    report_path = Path(path)
    report_path.write_text(await build_connectome_report(), encoding="utf-8")
    return report_path


async def write_connectome_report_json(path: str | Path) -> Path:
    report_path = Path(path)
    report_path.write_text(json.dumps(await build_connectome_report_data(), indent=2, sort_keys=True), encoding="utf-8")
    return report_path


async def write_connectome_headlines(path: str | Path) -> Path:
    report_path = Path(path)
    data = await build_connectome_report_data()
    headlines = {
        "pilot_archetype_accuracy": data["pilot"]["archetype_accuracy"],
        "full_archetype_accuracy": data["full"]["archetype_accuracy"],
        "full_slot_precision": data["full"]["slot_precision"],
        "live_run_count": data["live_run"]["run_count"],
        "seeded_case_count": data["seeded_retrograde"]["case_count"],
        "top_seeded_cause_kinds": sorted(data["seeded_retrograde"]["top_kind_counts"].keys()),
        "dominant_seeded_clusters": sorted(data["seeded_retrograde"]["dominant_cluster_counts"].keys()),
        "seeded_confidence_bands": sorted(data["seeded_retrograde"]["confidence_band_counts"].keys()),
        "seeded_calibrations": sorted(data["seeded_retrograde"]["calibration_counts"].keys()),
        "seeded_stabilities": sorted(data["seeded_retrograde"]["stability_counts"].keys()),
    }
    report_path.write_text(json.dumps(headlines, indent=2, sort_keys=True), encoding="utf-8")
    return report_path


async def write_connectome_status_markdown(path: str | Path) -> Path:
    report_path = Path(path)
    data = await build_connectome_report_data()
    seeded = data["seeded_retrograde"]
    lines = [
        "# CAM-SEQ Benchmark Status",
        "",
        f"- Full archetype accuracy: {data['full']['archetype_accuracy']:.2f}",
        f"- Full slot precision: {data['full']['slot_precision']:.2f}",
        f"- Live reviewed runs: {data['live_run']['run_count']}",
        f"- Seeded retrograde cases: {seeded['case_count']}",
        f"- Top seeded cause kinds: {', '.join(sorted(seeded['top_kind_counts'].keys()))}",
        f"- Dominant seeded clusters: {', '.join(sorted(seeded['dominant_cluster_counts'].keys()))}",
        f"- Seeded confidence bands: {', '.join(sorted(seeded['confidence_band_counts'].keys()))}",
        f"- Seeded calibrations: {', '.join(sorted(seeded['calibration_counts'].keys()))}",
        f"- Seeded stabilities: {', '.join(sorted(seeded['stability_counts'].keys()))}",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


async def write_connectome_manifest(path: str | Path, *, markdown_path: str | Path, json_path: str | Path) -> Path:
    report_path = Path(path)
    markdown_file = Path(markdown_path)
    json_file = Path(json_path)
    data = await build_connectome_report_data()
    manifest = {
        "generated_for": "cam-seq-connectome-benchmark",
        "summary": {
            "overall_task_count": int(data["full"]["task_count"]),
            "live_run_count": int(data["live_run"]["run_count"]),
            "seeded_case_count": int(data["seeded_retrograde"]["case_count"]),
        },
        "artifacts": [
            {
                "path": markdown_file.as_posix(),
                "kind": "markdown",
                "bytes": markdown_file.stat().st_size,
            },
            {
                "path": json_file.as_posix(),
                "kind": "json",
                "bytes": json_file.stat().st_size,
            },
        ]
    }
    report_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return report_path
