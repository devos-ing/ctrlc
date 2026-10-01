"""Run the installed ctrlc CLI against versioned local annotations."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

from PIL import Image, ImageOps

if __package__:
    from .scoring import IOU_THRESHOLD, score_scene, validate_annotation, write_overlay
else:
    from scoring import IOU_THRESHOLD, score_scene, validate_annotation, write_overlay


REPOSITORY = Path(__file__).resolve().parents[1]
PACKAGE_CODE_FILES = ("cli.py", "extraction.py", "hierarchy.py", "workflows.py",
                      "rendering.py", "assets/inspector.html")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _benchmark_checkout_code_hashes() -> dict[str, str]:
    return {f"ctrlc/{name}": _sha(REPOSITORY / "ctrlc" / name)
            for name in PACKAGE_CODE_FILES}


def _generated_entrypoint_source(cli: Path) -> tuple[bool, str | None]:
    """Accept only setuptools' direct ctrlc.cli:main console-script body."""
    if cli.is_symlink():
        return False, "CLI entrypoint is a symlink"
    try:
        source = cli.read_text(encoding="utf-8")
        actual = ast.dump(ast.parse(source), include_attributes=False)
        expected_source = (
            "import re\nimport sys\nfrom ctrlc.cli import main\n"
            "if __name__ == '__main__':\n"
            "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
            "    sys.exit(main())\n"
        )
        uv_expected_source = (
            "import sys\nfrom ctrlc.cli import main\n"
            "if __name__ == '__main__':\n"
            "    if sys.argv[0].endswith('-script.pyw'):\n"
            "        sys.argv[0] = sys.argv[0][:-11]\n"
            "    elif sys.argv[0].endswith('.exe'):\n"
            "        sys.argv[0] = sys.argv[0][:-4]\n"
            "    sys.exit(main())\n"
        )
        expected_sources = (expected_source, uv_expected_source)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as error:
        return False, f"CLI entrypoint source is unreadable or invalid: {error}"
    if any(actual == ast.dump(ast.parse(candidate), include_attributes=False)
           for candidate in expected_sources):
        return True, None
    return False, "CLI entrypoint source is not a recognized generated direct ctrlc.cli:main script"


def _python_interpreter_from_cli(cli: Path) -> Path | None:
    """Resolve the interpreter only after the command source matches its entrypoint template."""
    generated, _reason = _generated_entrypoint_source(cli)
    if not generated:
        return None
    try:
        first_line = cli.read_bytes().splitlines()[0].decode("utf-8")
    except (OSError, IndexError, UnicodeDecodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    try:
        parts = shlex.split(first_line[2:].strip())
    except ValueError:
        return None
    if not parts:
        return None
    interpreter = parts[0]
    args = parts[1:]
    if Path(interpreter).name == "env":
        if args and args[0] == "-S":
            args = args[1:]
        if (len(args) != 1 or "=" in args[0]):
            return None
        interpreter = shutil.which(args[0]) or ""
    elif args:
        # Do not omit interpreter flags such as -I when querying runtime state.
        return None
    if not interpreter or not Path(interpreter).name.startswith("python"):
        return None
    # Keep a venv's python path intact: resolving its symlink can escape the venv
    # and query a different site-packages directory than the console script uses.
    resolved = Path(interpreter).expanduser().absolute()
    return resolved if resolved.is_file() else None


def _installed_cli_provenance(cli: Path, cwd: Path) -> dict[str, Any]:
    source_valid, source_reason = _generated_entrypoint_source(cli)
    interpreter = _python_interpreter_from_cli(cli)
    base = {"status": "unknown", "entrypoint": str(cli), "entrypointSha256": _sha(cli),
            "interpreterExecutable": str(interpreter) if interpreter else None,
            "package": None, "packageRoot": None, "runtime": None,
            "codePaths": None, "codeHashes": None}
    if interpreter is None:
        base["reason"] = (source_reason if not source_valid else
                           "CLI is not a recognized Python console script; installed runtime metadata was not inferred")
        return base
    query = r"""
import hashlib, importlib.metadata, json, platform, sys, sysconfig
from pathlib import Path
try:
    import ctrlc
    distribution = importlib.metadata.distribution("ctrlc")
    registered = [entry.value for entry in distribution.entry_points
                  if entry.group == "console_scripts" and entry.name == "ctrlc"]
    registered_path = Path(sysconfig.get_path("scripts")).resolve() / "ctrlc"
    supplied_path = Path(sys.argv[1]).resolve()
    registration_valid = (registered == ["ctrlc.cli:main"]
                          and supplied_path == registered_path.resolve())
    package_root = Path(ctrlc.__file__).resolve().parent
    files = ("cli.py", "extraction.py", "hierarchy.py", "workflows.py",
             "rendering.py", "assets/inspector.html")
    paths = {name: str((package_root / name).resolve()) for name in files
             if (package_root / name).is_file()}
    hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
              for name, path in paths.items()}
    def version(name):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None
    print(json.dumps({"packageVersion": version("ctrlc"),
                      "packageRoot": str(package_root), "codePaths": paths,
                      "codeHashes": hashes,
                      "entrypointRegistration": {"values": registered,
                                                   "registeredPath": str(registered_path),
                                                   "suppliedPath": str(supplied_path),
                                                   "valid": registration_valid},
                      "runtime": {"python": sys.version, "executable": sys.executable,
                                  "platform": platform.platform(),
                                  "pillow": version("Pillow"), "numpy": version("numpy")}}))
except Exception as error:
    print(json.dumps({"error": f"{type(error).__name__}: {error}"}))
"""
    try:
        process = subprocess.run([str(interpreter), "-c", query, str(cli)], cwd=cwd,
                                 capture_output=True, text=True, timeout=15)
        payload = json.loads(process.stdout) if process.stdout.strip() else {}
        registration = payload.get("entrypointRegistration", {})
        if process.returncode == 0 and not payload.get("error") and registration.get("valid") is True:
            base.update({"status": "verified", "package": {"name": "ctrlc",
                          "version": payload.get("packageVersion")},
                         "packageRoot": payload.get("packageRoot"),
                         "entrypointRegistration": registration,
                         "runtime": payload.get("runtime"),
                         "codePaths": payload.get("codePaths"),
                         "codeHashes": payload.get("codeHashes")})
            return base
        base["reason"] = (payload.get("error") or process.stderr.strip()
                           or "CLI path/content does not match the registered ctrlc console entrypoint")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        base["reason"] = f"{type(error).__name__}: {error}"
    return base


def _verify_installed_package(provenance: dict[str, Any],
                              checkout_hashes: dict[str, str]) -> None:
    if provenance.get("status") != "verified" or not isinstance(provenance.get("codeHashes"), dict):
        raise RuntimeError("Unable to verify installed ctrlc code; "
                           f"benchmark stopped with unknown CLI metadata: {provenance.get('reason', 'unknown')}")
    package_root = Path(provenance["packageRoot"]).resolve()
    try:
        package_root.relative_to(REPOSITORY.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError("Installed CLI imports ctrlc from the source checkout; "
                           "install the frozen wheel outside the checkout")
    expected = {name.removeprefix("ctrlc/"): digest
                for name, digest in checkout_hashes.items()}
    actual = provenance["codeHashes"]
    mismatched = [name for name, digest in expected.items() if actual.get(name) != digest]
    if mismatched:
        raise RuntimeError("Installed ctrlc code does not match the benchmark checkout snapshot: "
                           + ", ".join(sorted(mismatched)))
    provenance["codeHashValidation"] = {"status": "matched",
                                        "files": sorted(expected),
                                        "reference": "benchmark checkout frozen snapshot"}


def _dependency_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _ensure_installed_integrity(cli: Path, provenance: dict[str, Any]) -> None:
    if _sha(cli) != provenance.get("entrypointSha256"):
        raise RuntimeError("Installed ctrlc console entrypoint changed during benchmarking")
    for name, path in (provenance.get("codePaths") or {}).items():
        expected = (provenance.get("codeHashes") or {}).get(name)
        if not expected or not Path(path).is_file() or _sha(Path(path)) != expected:
            raise RuntimeError(f"Installed ctrlc package file changed during benchmarking: {name}")


def _installed_cli(cli_value: str | None) -> Path:
    command = cli_value or shutil.which("ctrlc")
    if not command:
        raise RuntimeError("An installed ctrlc command is required; pass --cli PATH")
    path = Path(command).expanduser().absolute()
    try:
        path.relative_to(REPOSITORY.resolve())
    except ValueError:
        return path
    raise RuntimeError("Benchmark CLI must be installed outside the source checkout")


def _run_cli(cli: Path, args: list[str], cwd: Path,
             provenance: dict[str, Any] | None = None) -> tuple[dict[str, Any], float]:
    if provenance is not None:
        _ensure_installed_integrity(cli, provenance)
    started = time.perf_counter()
    process = subprocess.run([str(cli), *args], cwd=cwd, capture_output=True, text=True)
    elapsed = time.perf_counter() - started
    if provenance is not None:
        _ensure_installed_integrity(cli, provenance)
    if process.returncode:
        raise RuntimeError(f"Installed CLI failed ({process.returncode}): {process.stderr.strip()}")
    try:
        envelope = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Installed CLI returned invalid JSON: {process.stdout[:300]}") from error
    if not envelope.get("ok") or not isinstance(envelope.get("result"), dict):
        raise RuntimeError(f"Installed CLI returned an error: {envelope.get('error')}")
    return envelope["result"], elapsed


def _fixture_paths(manifest_dir: Path, fixture: dict[str, Any]) -> dict[str, Path | None]:
    def resolve(value: str | None) -> Path | None:
        return (manifest_dir / value).resolve() if value else None
    return {"screenshot": resolve(fixture.get("screenshot")),
            "ocr": resolve(fixture.get("ocr")),
            "annotation": resolve(fixture.get("annotation")),
            "legacy_scene": resolve(fixture.get("legacy_scene"))}


def _verify_source(fixture: dict[str, Any], screenshot: Path) -> None:
    if not screenshot.is_file():
        raise FileNotFoundError(f"Missing screenshot for {fixture.get('id')}: {screenshot}")
    digest = _sha(screenshot)
    if digest != fixture.get("source_sha256"):
        raise ValueError(f"Screenshot hash mismatch for {fixture.get('id')}")
    with Image.open(screenshot) as raw:
        image = ImageOps.exif_transpose(raw)
    if list(image.size) != [fixture.get("width"), fixture.get("height")]:
        raise ValueError(f"Screenshot dimensions mismatch for {fixture.get('id')}")


def _quality_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    depth_items = [item for item in items if not item["legacy"]]
    if not depth_items:
        return {"status": "unavailable"}
    tp = sum(item["nodeMetrics"]["aggregate"]["tp"] for item in depth_items)
    fp = sum(item["nodeMetrics"]["aggregate"]["fp"] for item in depth_items)
    fn = sum(item["nodeMetrics"]["aggregate"]["fn"] for item in depth_items)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"micro": {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
                      "recall": recall, "f1": 2 * precision * recall / (precision + recall)
                      if precision + recall else 0.0},
            "macroPrecision": statistics.mean(item["nodeMetrics"]["aggregate"]["precision"]
                                               for item in depth_items),
            "macroRecall": statistics.mean(item["nodeMetrics"]["aggregate"]["recall"]
                                            for item in depth_items),
            "macroF1": statistics.mean(item["nodeMetrics"]["aggregate"]["f1"]
                                        for item in depth_items),
            "screens": len(depth_items)}


def _defined_mean(values: list[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    return statistics.mean(defined) if defined else None


def _nearest_rank_p90(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(0.90 * len(values)) - 1)]


def _matched_box_summary(scores: list[dict[str, Any]]) -> tuple[float | None, int]:
    values = [match["iou"] for score in scores for match in score.get("matched", [])]
    return (statistics.mean(values) if values else None), len(values)


def run_benchmark(manifest_path: str | Path, output_dir: str | Path, *,
                  cli_path: str | None = None, split: str = "tuning", max_depth: int = 3,
                  repetitions: int = 10, include_refine_track: bool = True,
                  include_native_ocr: bool = False) -> dict[str, Any]:
    if split not in {"tuning", "holdout", "all"}:
        raise ValueError("split must be tuning, holdout, or all")
    if type(max_depth) is not int or not 1 <= max_depth <= 3:
        raise ValueError("max_depth must be 1, 2, or 3")
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    cli = _installed_cli(cli_path)
    manifest_path = Path(manifest_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text())
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("Fixture manifest must contain a fixtures array")
    selected = [fixture for fixture in fixtures
                if split == "all" or fixture.get("split") == split]
    if not selected:
        raise ValueError(f"Manifest contains no fixtures for split {split}")
    run_root = output_dir / "artifacts"
    run_root.mkdir(exist_ok=True)
    per_screen: list[dict[str, Any]] = []
    comparison: dict[str, list[dict[str, Any]]] = {"legacy": []}
    comparison.update({f"depth{depth}": [] for depth in range(1, max_depth + 1)})
    if include_native_ocr:
        comparison["nativeDepth1"] = []
    cost_rows = []

    with tempfile.TemporaryDirectory(prefix="ctrlc-benchmark-outside-") as temp_folder:
        cwd = Path(temp_folder)
        checkout_code_hashes = _benchmark_checkout_code_hashes()
        installed_cli = _installed_cli_provenance(cli, cwd)
        _verify_installed_package(installed_cli, checkout_code_hashes)
        for fixture in selected:
            paths = _fixture_paths(manifest_path.parent, fixture)
            screenshot, ocr, annotation_path = paths["screenshot"], paths["ocr"], paths["annotation"]
            if screenshot is None or ocr is None or annotation_path is None:
                raise ValueError(f"Fixture {fixture.get('id')} needs screenshot, OCR, and annotation paths")
            _verify_source(fixture, screenshot)
            if not ocr.is_file():
                raise FileNotFoundError(f"Missing fixed OCR data for {fixture['id']}: {ocr}")
            if not annotation_path.is_file():
                raise FileNotFoundError(f"Missing annotation for {fixture['id']}: {annotation_path}")
            annotation = json.loads(annotation_path.read_text())
            annotation["nodes"] = validate_annotation(annotation, fixture)
            fixture_id = fixture["id"]
            screen_result = {"id": fixture_id, "split": fixture.get("split"),
                             "sourceSha256": fixture["source_sha256"],
                             "ocrSha256": _sha(ocr),
                             "annotationVersion": annotation.get("version"),
                             "annotationProvenance": annotation.get("annotation_provenance", {}),
                             "roi": fixture["roi"], "configurations": {}}
            config_results = {"legacy": (None, True)}
            config_results.update({f"depth{depth}": (depth, False)
                                   for depth in range(1, max_depth + 1)})
            scene_paths: dict[str, Path] = {}
            for config_name, (depth, legacy) in config_results.items():
                work_dir = run_root / fixture_id / config_name
                work_dir.mkdir(parents=True, exist_ok=True)
                args = ["extract", str(screenshot), "--out", str(work_dir / "extract"),
                        "--roi", ",".join(map(str, fixture["roi"])), "--ocr-json", str(ocr)]
                if depth is not None:
                    args.extend(["--depth", str(depth)])
                samples = []
                final_result = None
                for repetition in range(repetitions):
                    result, wall_seconds = _run_cli(cli, args, cwd, installed_cli)
                    final_result = result
                    run_record = json.loads(Path(result["artifacts"]["run"]).read_text())
                    artifact_bytes = sum(Path(path).stat().st_size
                                         for path in result["artifacts"].values()
                                         if Path(path).is_file())
                    samples.append({"wallSeconds": wall_seconds,
                                    "reportedSeconds": run_record.get("elapsedSeconds"),
                                    "artifactBytes": artifact_bytes,
                                    "cacheHit": run_record.get("cacheHit"),
                                    "measurementCacheHit": run_record.get("measurementCacheHit"),
                                    "hierarchyCacheHit": run_record.get("hierarchyCacheHit"),
                                    "ocrInvocations": run_record.get("ocrInvocations", 0),
                                    "ocrSeconds": run_record.get("ocrSeconds"),
                                    "measurementSeconds": run_record.get("measurementSeconds"),
                                    "hierarchySeconds": run_record.get("hierarchySeconds"),
                                    "hierarchyPassSecondsThisRun": run_record.get("hierarchyPassSecondsThisRun", {}),
                                    "hierarchyPassSecondsAddedThisRun": run_record.get("hierarchyPassSecondsAddedThisRun", {}),
                                    "renderingSeconds": run_record.get("renderingSeconds"),
                                    "peakMemoryBytes": run_record.get("processPeakMemoryBytes")})
                assert final_result is not None
                scene_path = Path(final_result["artifacts"]["scene"])
                scene = json.loads(scene_path.read_text())
                artifact_path = Path(final_result["artifacts"]["measurements"]) if not legacy else None
                if legacy:
                    # Legacy has no measured evidence artifact; retain the CLI's emitted tree as-is.
                    score = score_scene(scene, annotation, depth=None, legacy=True)
                else:
                    score = score_scene(scene, annotation, depth=depth,
                                        artifact_path=artifact_path,
                                        expected_source_hash=fixture["source_sha256"])
                render_result, render_wall = _run_cli(cli,
                    ["render", str(scene_path), str(screenshot), "--out", str(work_dir / "rendered.html")],
                    cwd, installed_cli)
                score["rendering"] = {"wallSeconds": render_wall, "bytes": render_result.get("bytes"),
                                      "llmCalls": render_result.get("llmCalls")}
                overlay_path = output_dir / "overlays" / f"{fixture_id}-{config_name}.png"
                write_overlay(screenshot, fixture["roi"], scene, annotation, overlay_path,
                              depth=depth, legacy=legacy)
                score["overlay"] = str(overlay_path)
                screen_result["configurations"][config_name] = score
                comparison[config_name].append(score)
                scene_paths[config_name] = scene_path
                def measurement_cache_hit(sample: dict[str, Any]) -> bool | None:
                    cached = sample.get("measurementCacheHit")
                    if cached is None:
                        cached = sample.get("cacheHit")
                    return cached if type(cached) is bool else None

                fresh_samples = [sample["wallSeconds"] for sample in samples
                                 if measurement_cache_hit(sample) is False]
                warm_samples = [sample["wallSeconds"] for sample in samples
                                if measurement_cache_hit(sample) is True]
                unknown_cache_samples = sum(measurement_cache_hit(sample) is None for sample in samples)
                all_wall_samples = [sample["wallSeconds"] for sample in samples]
                cost_rows.append({"fixture": fixture_id, "configuration": config_name,
                                  "sampling": "cache state taken from CLI run metadata; unknown remains unclassified",
                                  "sampleCacheStates": ["warm" if measurement_cache_hit(sample) else
                                                         "fresh" if measurement_cache_hit(sample) is False
                                                         else "unknown" for sample in samples],
                                  "samples": len(samples), "medianWallSeconds": statistics.median(
                                      all_wall_samples),
                                  "p90WallSeconds": _nearest_rank_p90(all_wall_samples),
                                  "freshSamples": len(fresh_samples),
                                  "warmSamples": len(warm_samples),
                                  "unknownCacheSamples": unknown_cache_samples,
                                  "freshMedianWallSeconds": statistics.median(fresh_samples) if fresh_samples else None,
                                  "warmMedianWallSeconds": statistics.median(warm_samples) if warm_samples else None,
                                  "samplesDetail": samples})

            if include_refine_track and max_depth >= 2:
                seed = scene_paths["depth1"]
                for depth in range(2, max_depth + 1):
                    refine_dir = run_root / fixture_id / f"refine{depth}"
                    args = ["refine", str(seed), str(screenshot), "--out", str(refine_dir),
                            "--depth", str(depth)]
                    samples = []
                    refined_result = None
                    for _ in range(repetitions):
                        refined_result, wall_seconds = _run_cli(cli, args, cwd, installed_cli)
                        run_record = json.loads(Path(refined_result["artifacts"]["run"]).read_text())
                        artifact_bytes = sum(Path(path).stat().st_size
                                             for path in refined_result["artifacts"].values()
                                             if Path(path).is_file())
                        samples.append({"wallSeconds": wall_seconds,
                                        "reportedSeconds": run_record.get("elapsedSeconds"),
                                        "artifactBytes": artifact_bytes,
                                        "ocrInvocations": run_record.get("ocrInvocations"),
                                        "measurementCacheHit": run_record.get("measurementCacheHit"),
                                        "hierarchySeconds": run_record.get("hierarchySeconds"),
                                        "hierarchyPassSecondsThisRun": run_record.get("hierarchyPassSecondsThisRun", {}),
                                        "hierarchyPassSecondsAddedThisRun": run_record.get("hierarchyPassSecondsAddedThisRun", {}),
                                        "renderingSeconds": run_record.get("renderingSeconds"),
                                        "peakMemoryBytes": run_record.get("processPeakMemoryBytes")})
                    assert refined_result is not None
                    refine_scene_data = json.loads(Path(refined_result["artifacts"]["scene"]).read_text())
                    artifact_path = Path(refined_result["artifacts"]["measurements"])
                    refine_score = score_scene(refine_scene_data, annotation, depth=depth,
                                               artifact_path=artifact_path,
                                               expected_source_hash=fixture["source_sha256"])
                    screen_result["configurations"][f"refine{depth}"] = refine_score
                    screen_result["configurations"][f"refine{depth}"]["mode"] = "saved-evidence-refine"
                    cost_rows.append({"fixture": fixture_id, "configuration": f"refine{depth}",
                                      "sampling": "saved-evidence refinement; no OCR",
                                      "samples": len(samples), "medianWallSeconds": statistics.median(
                                          sample["wallSeconds"] for sample in samples),
                                      "p90WallSeconds": _nearest_rank_p90([sample["wallSeconds"] for sample in samples]),
                                      "samplesDetail": samples})
            if include_native_ocr:
                native_dir = run_root / fixture_id / "native-depth1"
                native_args = ["extract", str(screenshot), "--out", str(native_dir / "extract"),
                               "--roi", ",".join(map(str, fixture["roi"])), "--depth", "1", "--inspector"]
                samples = []
                native_result = None
                for _ in range(repetitions):
                    native_result, wall_seconds = _run_cli(cli, native_args, cwd, installed_cli)
                    run_record = json.loads(Path(native_result["artifacts"]["run"]).read_text())
                    artifact_bytes = sum(Path(path).stat().st_size
                                         for path in native_result["artifacts"].values()
                                         if Path(path).is_file())
                    samples.append({"wallSeconds": wall_seconds,
                                    "reportedSeconds": run_record.get("elapsedSeconds"),
                                    "artifactBytes": artifact_bytes,
                                    "cacheHit": run_record.get("cacheHit"),
                                    "measurementCacheHit": run_record.get("measurementCacheHit"),
                                    "hierarchyCacheHit": run_record.get("hierarchyCacheHit"),
                                    "ocrInvocations": run_record.get("ocrInvocations", 0),
                                    "ocrSeconds": run_record.get("ocrSeconds"),
                                    "helperCompilationSeconds": run_record.get("nativeOcrHelperCompilationSeconds"),
                                    "measurementSeconds": run_record.get("measurementSeconds"),
                                    "hierarchySeconds": run_record.get("hierarchySeconds"),
                                    "hierarchyPassSecondsThisRun": run_record.get("hierarchyPassSecondsThisRun", {}),
                                    "renderingSeconds": run_record.get("renderingSeconds"),
                                    "peakMemoryBytes": run_record.get("processPeakMemoryBytes")})
                assert native_result is not None
                native_scene_path = Path(native_result["artifacts"]["scene"])
                native_scene = json.loads(native_scene_path.read_text())
                native_score = score_scene(native_scene, annotation, depth=1,
                                           artifact_path=native_result["artifacts"]["measurements"],
                                           expected_source_hash=fixture["source_sha256"])
                native_overlay = output_dir / "overlays" / f"{fixture_id}-native-depth1.png"
                write_overlay(screenshot, fixture["roi"], native_scene, annotation, native_overlay,
                              depth=1)
                native_score["overlay"] = str(native_overlay)
                native_score["mode"] = "native-ocr"
                screen_result["configurations"]["nativeDepth1"] = native_score
                comparison["nativeDepth1"].append(native_score)
                cost_rows.append({"fixture": fixture_id, "configuration": "nativeDepth1",
                                  "sampling": "native OCR, first helper compile and warm cache hits",
                                  "samples": len(samples), "medianWallSeconds": statistics.median(
                                      sample["wallSeconds"] for sample in samples),
                                  "p90WallSeconds": _nearest_rank_p90([sample["wallSeconds"] for sample in samples]),
                                  "freshMedianWallSeconds": statistics.median(
                                      [sample["wallSeconds"] for sample in samples if not sample["measurementCacheHit"]])
                                      if any(not sample["measurementCacheHit"] for sample in samples) else None,
                                  "warmMedianWallSeconds": statistics.median(
                                      [sample["wallSeconds"] for sample in samples if sample["measurementCacheHit"]])
                                      if any(sample["measurementCacheHit"] for sample in samples) else None,
                                  "samplesDetail": samples})
            per_screen.append(screen_result)

    comparison_rows = []
    for configuration, scores in comparison.items():
        if configuration == "legacy":
            tp = sum(item["nodeMetrics"]["levelAgnostic"]["tp"] for item in scores)
            fp = sum(item["nodeMetrics"]["levelAgnostic"]["fp"] for item in scores)
            fn = sum(item["nodeMetrics"]["levelAgnostic"]["fn"] for item in scores)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            mean_iou, matched_count = _matched_box_summary(scores)
            comparison_rows.append({"configuration": configuration, "semanticLevels": "not assigned",
                                    "precision": precision, "recall": recall, "f1": f1,
                                    "matchedBoxMeanIoU": mean_iou, "matchedBoxCount": matched_count,
                                    "parentEdgeF1": _defined_mean([item["parentEdgeF1"]["f1"] for item in scores]),
                                    "fragmentedAtomicAssets": sum(item["fragmentation"]["atomicAssetsFragmented"] for item in scores),
                                    "redundantPieces": sum(item["fragmentation"]["redundantPieces"] for item in scores),
                                    "overmerges": sum(item["overmerges"]["count"] for item in scores),
                                    "requiredControlLosses": sum(item["requiredControlLoss"]["count"] for item in scores),
                                    "evidenceIntegrityFailures": None})
            continue
        summary = _quality_summary(scores)
        mean_iou, matched_count = _matched_box_summary(scores)
        per_level = {}
        for level in sorted({level for item in scores
                             for level in item["nodeMetrics"].get("perLevel", {})}):
            level_scores = [item["nodeMetrics"]["perLevel"][level]
                            for item in scores if level in item["nodeMetrics"].get("perLevel", {})]
            per_level[level] = {"macroPrecision": statistics.mean(item["precision"] for item in level_scores),
                                "macroRecall": statistics.mean(item["recall"] for item in level_scores),
                                "macroF1": statistics.mean(item["f1"] for item in level_scores)}
        comparison_rows.append({"configuration": configuration, "semanticLevels": "matched by level",
                                "precision": summary["micro"]["precision"],
                                "recall": summary["micro"]["recall"], "f1": summary["micro"]["f1"],
                                "macroPrecision": summary["macroPrecision"],
                                "macroRecall": summary["macroRecall"], "macroF1": summary["macroF1"],
                                "perLevel": per_level,
                                "parentEdgeF1": _defined_mean([item["parentEdgeF1"]["f1"] for item in scores]),
                                "matchedBoxMeanIoU": mean_iou,
                                "matchedBoxCount": matched_count,
                                "fragmentedAtomicAssets": sum(item["fragmentation"]["atomicAssetsFragmented"] for item in scores),
                                "redundantPieces": sum(item["fragmentation"]["redundantPieces"] for item in scores),
                                "overmerges": sum(item["overmerges"]["count"] for item in scores),
                                "requiredControlLosses": sum(item["requiredControlLoss"]["count"] for item in scores),
                                "evidenceIntegrityFailures": sum(not item["evidenceIntegrity"]["valid"] for item in scores)})
    result = {"schemaVersion": 1,
              "manifest": str(manifest_path), "split": split,
              "matching": {"method": "deterministic descending-IoU greedy one-to-one",
                           "threshold": IOU_THRESHOLD, "typeCompatibility": "exact type, or section/container"},
              "provenance": {"annotationsHumanVerified": all(
                  item.get("annotation_provenance", {}).get("human_verified") is True
                  for item in [json.loads(paths["annotation"].read_text())
                               for paths in (_fixture_paths(manifest_path.parent, f) for f in selected)]),
                  "splitFamilies": sorted(set(f.get("source_family", "unknown") for f in selected))},
              "environment": {"benchmarkRunner": {"python": sys.version,
                                                       "executable": sys.executable,
                                                       "platform": platform.platform(),
                                                       "pillow": _dependency_version("Pillow"),
                                                       "numpy": _dependency_version("numpy")},
                              "benchmarkCheckoutCodeHashes": checkout_code_hashes,
                              "installedCli": installed_cli},
              "repetitions": repetitions, "screens": per_screen,
              "ocrTracks": {"grouping": "fixed supplied OCR",
                            "nativeVision": "included" if include_native_ocr else "not run"},
              "comparison": comparison_rows, "costs": cost_rows}
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    with (output_dir / "comparison.csv").open("w", newline="") as handle:
        fieldnames = list(dict.fromkeys(key for row in comparison_rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        csv_rows = [{key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                     for key, value in row.items()} for row in comparison_rows]
        writer.writerows(csv_rows)
    (output_dir / "per-screen.json").write_text(json.dumps(per_screen, ensure_ascii=False, indent=2) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark ctrlc hierarchy output against local annotations")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("manifest.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cli", help="path to an installed ctrlc executable outside the source checkout")
    parser.add_argument("--split", choices=("tuning", "holdout", "all"), default="tuning")
    parser.add_argument("--max-depth", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--no-refine-track", action="store_true")
    parser.add_argument("--native-ocr-track", action="store_true",
                        help="run an additional native Vision OCR depth-one cost track")
    args = parser.parse_args(argv)
    result = run_benchmark(args.manifest, args.out, cli_path=args.cli, split=args.split,
                           max_depth=args.max_depth, repetitions=args.repetitions,
                           include_refine_track=not args.no_refine_track,
                           include_native_ocr=args.native_ocr_track)
    print(json.dumps({"result": str((args.out / "result.json").resolve()),
                      "screens": len(result["screens"]), "comparison": result["comparison"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
