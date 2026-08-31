import json
import hashlib
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from .build import build_cmake, build_direct
from .models import BuildVariant, ProjectConfig
from .utils import effective_jobs


def detect_mode(target: Path) -> str:
    """
    Determine build mode:
      - 'file'   : target is a single source file
      - 'cmake'  : target directory contains CMakeLists.txt
      - 'folder' : target is a directory without CMakeLists.txt
    """
    if target.is_file():
        return "file"
    if not target.is_dir():
        raise FileNotFoundError(f"Target not found: {target}")
    if (target / "CMakeLists.txt").exists():
        return "cmake"
    return "folder"


def _run_direct_matrix(
    sources: list[Path],
    include_dir: Path,
    out_dir: Path,
    output_name: str,
    variants: list[BuildVariant],
    config: ProjectConfig,
    extra_args: list[str],
) -> int:
    """Run all variants in direct compilation mode."""
    summary: list[dict] = []
    had_failure = False
    run_id = uuid4().hex
    fingerprints = {
        variant.name: _build_fingerprint(
            "direct", variant, config, sources=sources, extra_args=extra_args
        )
        for variant in variants
    }
    resumed = _load_resumable_results(out_dir, output_name, fingerprints) if config.resume else {}
    _remove_previous_outputs(out_dir, output_name, keep_variants=set(resumed))

    try:
        if config.parallel_variants > 1:
            with ProcessPoolExecutor(max_workers=config.parallel_variants) as executor:
                futures = {}
                for variant in variants:
                    if variant.name in resumed:
                        summary.append(resumed[variant.name])
                        _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                        continue
                    fut = executor.submit(
                        build_direct,
                        sources,
                        include_dir,
                        out_dir,
                        output_name,
                        variant,
                        config,
                        extra_args or None,
                        fingerprints[variant.name],
                    )
                    futures[fut] = variant

                for fut in as_completed(futures):
                    variant = futures[fut]
                    try:
                        metadata = fut.result()
                        summary.append(metadata)
                        print(f"  [{variant.compiler}] {variant.name} -> {metadata['artifact']}")
                    except RuntimeError as e:
                        had_failure = had_failure or not variant.allow_failure
                        label = "ALLOWED FAILURE" if variant.allow_failure else "FAILED"
                        print(f"  [{variant.compiler}] {variant.name} {label}: {e}", file=sys.stderr)
                        summary.append(
                            {
                                "name": variant.name,
                                "error": str(e),
                                "allowed_failure": variant.allow_failure,
                            }
                        )
                    _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                    if had_failure and config.stop_on_error:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
        else:
            for variant in variants:
                print(f"\n=== [{variant.compiler} -std={variant.standard}] {variant.name} ===")
                if variant.name in resumed:
                    summary.append(resumed[variant.name])
                    print(f"    -> {resumed[variant.name]['artifact']} (resumed)")
                    _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                    continue
                try:
                    metadata = build_direct(
                        sources=sources,
                        include_dir=include_dir,
                        out_dir=out_dir,
                        output_name=output_name,
                        variant=variant,
                        config=config,
                        extra_args=extra_args or None,
                        fingerprint=fingerprints[variant.name],
                    )
                    summary.append(metadata)
                    print(f"    -> {metadata['artifact']}")
                except RuntimeError as e:
                    had_failure = had_failure or not variant.allow_failure
                    label = "ALLOWED FAILURE" if variant.allow_failure else "FAILED"
                    print(f"    {label}: {e}", file=sys.stderr)
                    summary.append(
                        {
                            "name": variant.name,
                            "error": str(e),
                            "allowed_failure": variant.allow_failure,
                        }
                    )
                _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                if had_failure and config.stop_on_error:
                    break
    except KeyboardInterrupt:
        _write_summary(out_dir, summary, run_id=run_id, complete=False, interrupted=True)
        return 130

    _write_summary(out_dir, summary, run_id=run_id, complete=True)
    return 1 if had_failure else 0


def _run_cmake_matrix(
    root: Path,
    config: ProjectConfig,
    out_dir: Path,
    variants: list[BuildVariant],
    build_type: str,
) -> int:
    """Run all variants in CMake mode."""
    summary: list[dict] = []
    had_failure = False
    run_id = uuid4().hex
    fingerprints = {
        variant.name: _build_fingerprint(
            "cmake", variant, config, root=root, build_type=build_type
        )
        for variant in variants
    }
    resumed = (
        _load_resumable_results(out_dir, config.cmake_target, fingerprints)
        if config.resume
        else {}
    )
    _remove_previous_outputs(out_dir, config.cmake_target, keep_variants=set(resumed))

    try:
        if config.parallel_variants > 1:
            jobs_per_variant = max(
                1, effective_jobs(config.jobs) // config.parallel_variants
            )
            worker_config = replace(config, jobs=jobs_per_variant)
            with ProcessPoolExecutor(max_workers=config.parallel_variants) as executor:
                futures = {}
                for variant in variants:
                    if variant.name in resumed:
                        summary.append(resumed[variant.name])
                        _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                        continue
                    future = executor.submit(
                        build_cmake,
                        root,
                        worker_config,
                        out_dir,
                        variant,
                        build_type,
                        fingerprints[variant.name],
                    )
                    futures[future] = variant

                for future in as_completed(futures):
                    variant = futures[future]
                    try:
                        metadata = future.result()
                        summary.append(metadata)
                        print(f"  [{variant.compiler}] {variant.name} -> {metadata['artifact']}")
                    except (RuntimeError, FileNotFoundError) as error:
                        had_failure = had_failure or not variant.allow_failure
                        label = "ALLOWED FAILURE" if variant.allow_failure else "FAILED"
                        print(
                            f"  [{variant.compiler}] {variant.name} {label}: {error}",
                            file=sys.stderr,
                        )
                        summary.append(
                            {
                                "name": variant.name,
                                "error": str(error),
                                "allowed_failure": variant.allow_failure,
                            }
                        )
                    _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                    if had_failure and config.stop_on_error:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
        else:
            for variant in variants:
                print(f"\n=== [{variant.compiler}] {variant.name} ===")
                if variant.name in resumed:
                    summary.append(resumed[variant.name])
                    print(f"    -> {resumed[variant.name]['artifact']} (resumed)")
                    _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                    continue
                try:
                    metadata = build_cmake(
                        root=root,
                        config=config,
                        out_dir=out_dir,
                        variant=variant,
                        build_type=build_type,
                        fingerprint=fingerprints[variant.name],
                    )
                    summary.append(metadata)
                    print(f"    -> {metadata['artifact']}")
                except (RuntimeError, FileNotFoundError) as error:
                    had_failure = had_failure or not variant.allow_failure
                    label = "ALLOWED FAILURE" if variant.allow_failure else "FAILED"
                    print(f"    {label}: {error}", file=sys.stderr)
                    summary.append(
                        {
                            "name": variant.name,
                            "error": str(error),
                            "allowed_failure": variant.allow_failure,
                        }
                    )
                _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                if had_failure and config.stop_on_error:
                    break
    except KeyboardInterrupt:
        _write_summary(out_dir, summary, run_id=run_id, complete=False, interrupted=True)
        return 130

    _write_summary(out_dir, summary, run_id=run_id, complete=True)
    return 1 if had_failure else 0


def _remove_previous_outputs(
    out_dir: Path, output_name: str, *, keep_variants: set[str] | None = None
) -> None:
    preserved = set()
    for variant_name in keep_variants or set():
        prefix = f"{output_name}__{variant_name}"
        preserved.update({prefix, f"{prefix}.json", f"{prefix}.compile_commands.json"})
    for path in out_dir.glob(f"{output_name}__*"):
        if path.name not in preserved and (path.is_file() or path.is_symlink()):
            path.unlink()


def _load_resumable_results(
    out_dir: Path, output_name: str, fingerprints: dict[str, str]
) -> dict[str, dict]:
    resumed = {}
    for variant_name, fingerprint in fingerprints.items():
        metadata_path = out_dir / f"{output_name}__{variant_name}.json"
        if not metadata_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            artifact = Path(metadata["artifact"])
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if metadata.get("fingerprint") != fingerprint:
            continue
        if metadata.get("artifact_sha256") != artifact_hash:
            continue
        resumed[variant_name] = {**metadata, "resumed": True}
    return resumed


def _build_fingerprint(
    mode: str,
    variant: BuildVariant,
    config: ProjectConfig,
    *,
    sources: list[Path] | None = None,
    root: Path | None = None,
    extra_args: list[str] | None = None,
    build_type: str = "",
) -> str:
    config_data = asdict(config)
    for operational_key in (
        "clean",
        "out_dir",
        "parallel_variants",
        "resume",
        "stop_on_error",
        "verbose",
    ):
        config_data.pop(operational_key, None)

    source_paths = sources or _cmake_input_files(root)
    compiler_command = shlex.split(variant.cxx_compiler or variant.compiler)[0]
    payload = {
        "mode": mode,
        "variant": asdict(variant),
        "config": config_data,
        "build_type": build_type,
        "extra_args": extra_args or [],
        "compiler": _compiler_identity(compiler_command),
        "environment_setup_sha256": _optional_file_hash(config.env_setup),
        "toolchain_sha256": _optional_file_hash(config.cmake_toolchain_file),
        "sources": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in source_paths
            if path.is_file()
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _compiler_identity(command: str) -> dict[str, str]:
    resolved = shutil.which(command) or command
    try:
        result = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, check=False
        )
        output = result.stdout.strip() or result.stderr.strip()
        version = output.splitlines()[0] if output else ""
    except OSError:
        version = ""
    return {"path": resolved, "version": version}


def _optional_file_hash(path_value: str) -> str:
    if not path_value:
        return ""
    try:
        return hashlib.sha256(Path(path_value).read_bytes()).hexdigest()
    except OSError:
        return ""


def _cmake_input_files(root: Path | None) -> list[Path]:
    if root is None:
        return []
    extensions = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".cmake"}
    ignored_parts = {".git", ".out", "__pycache__"}
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not ignored_parts.intersection(path.parts)
        and (path.suffix.lower() in extensions or path.name == "CMakeLists.txt")
    )


def _atomic_write_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _persist_run_state(
    out_dir: Path,
    summary: list[dict],
    *,
    run_id: str,
    complete: bool,
    interrupted: bool = False,
) -> None:
    _atomic_write_json(out_dir / "build_summary.json", summary)

    artifacts = []
    for result in summary:
        if result.get("allowed_failure") and "error" in result:
            status = "allowed_failure"
        else:
            status = "failed" if "error" in result else "succeeded"
        entry = {"variant": result["name"], "status": status}
        artifact_value = result.get("artifact")
        if artifact_value:
            artifact = Path(artifact_value)
            if artifact.exists():
                entry["path"] = str(artifact.relative_to(out_dir))
                entry["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if "error" in result:
            entry["error"] = result["error"]
        artifacts.append(entry)

    _atomic_write_json(
        out_dir / "manifest.json",
        {
            "run_id": run_id,
            "complete": complete,
            "interrupted": interrupted,
            "artifacts": artifacts,
        },
    )


def _write_summary(
    out_dir: Path,
    summary: list[dict],
    *,
    run_id: str,
    complete: bool,
    interrupted: bool = False,
) -> None:
    _persist_run_state(
        out_dir,
        summary,
        run_id=run_id,
        complete=complete,
        interrupted=interrupted,
    )
    summary_path = out_dir / "build_summary.json"

    succeeded = sum(1 for s in summary if "error" not in s)
    allowed_failures = sum(1 for s in summary if s.get("allowed_failure") and "error" in s)
    failed = len(summary) - succeeded - allowed_failures
    print(
        f"\nDone: {succeeded} succeeded, {allowed_failures} allowed failures, {failed} failed."
    )
    print(f"Artifacts: {out_dir}")
    print(f"Summary:   {summary_path}")
