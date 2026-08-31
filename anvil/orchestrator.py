import json
import hashlib
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

from .build import build_cmake, build_direct
from .models import BuildVariant, ProjectConfig


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
    _remove_previous_outputs(out_dir, output_name)

    try:
        if config.parallel_variants > 1:
            with ProcessPoolExecutor(max_workers=config.parallel_variants) as executor:
                futures = {}
                for variant in variants:
                    fut = executor.submit(
                        build_direct,
                        sources,
                        include_dir,
                        out_dir,
                        output_name,
                        variant,
                        config,
                        extra_args or None,
                    )
                    futures[fut] = variant

                for fut in as_completed(futures):
                    variant = futures[fut]
                    try:
                        metadata = fut.result()
                        summary.append(metadata)
                        print(f"  [{variant.compiler}] {variant.name} -> {metadata['artifact']}")
                    except RuntimeError as e:
                        had_failure = True
                        print(f"  [{variant.compiler}] {variant.name} FAILED: {e}", file=sys.stderr)
                        summary.append({"name": variant.name, "error": str(e)})
                    _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
                    if had_failure and config.stop_on_error:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
        else:
            for variant in variants:
                print(f"\n=== [{variant.compiler} -std={variant.standard}] {variant.name} ===")
                try:
                    metadata = build_direct(
                        sources=sources,
                        include_dir=include_dir,
                        out_dir=out_dir,
                        output_name=output_name,
                        variant=variant,
                        config=config,
                        extra_args=extra_args or None,
                    )
                    summary.append(metadata)
                    print(f"    -> {metadata['artifact']}")
                except RuntimeError as e:
                    had_failure = True
                    print(f"    FAILED: {e}", file=sys.stderr)
                    summary.append({"name": variant.name, "error": str(e)})
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
    _remove_previous_outputs(out_dir, config.cmake_target)

    try:
        for variant in variants:
            print(f"\n=== [{variant.compiler}] {variant.name} ===")
            try:
                metadata = build_cmake(
                    root=root,
                    config=config,
                    out_dir=out_dir,
                    variant=variant,
                    build_type=build_type,
                )
                summary.append(metadata)
                print(f"    -> {metadata['artifact']}")
            except (RuntimeError, FileNotFoundError) as e:
                had_failure = True
                print(f"    FAILED: {e}", file=sys.stderr)
                summary.append({"name": variant.name, "error": str(e)})
            _persist_run_state(out_dir, summary, run_id=run_id, complete=False)
            if had_failure and config.stop_on_error:
                break
    except KeyboardInterrupt:
        _write_summary(out_dir, summary, run_id=run_id, complete=False, interrupted=True)
        return 130

    _write_summary(out_dir, summary, run_id=run_id, complete=True)
    return 1 if had_failure else 0


def _remove_previous_outputs(out_dir: Path, output_name: str) -> None:
    for path in out_dir.glob(f"{output_name}__*"):
        if path.is_file() or path.is_symlink():
            path.unlink()


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
        entry = {"variant": result["name"], "status": "failed" if "error" in result else "succeeded"}
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
    failed = len(summary) - succeeded
    print(f"\nDone: {succeeded} succeeded, {failed} failed.")
    print(f"Artifacts: {out_dir}")
    print(f"Summary:   {summary_path}")
