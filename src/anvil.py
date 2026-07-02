#!/usr/bin/env python3
"""
Anvil, C/C++ build-matrix tool.

Builds a C/C++ target multiple times with variant-specific compilers, flags,
and defines. Supports three modes:

  1. Single .cpp file   — compiles directly (no CMake).
  2. Folder             — compiles all .cpp/.c files recursively (no CMake).
  3. CMake project      — uses CMakeLists.txt if present in target directory.

Config discovery:
  - If anvil.project.json and anvil.variants.<preset>.json exist next to the
    target, they are used automatically.
  - Otherwise built-in defaults are applied.

anvil.project.json format:
  {
    "name": "my_project",         // project name (used in output paths)
    "build_dir": "/build/myproj", // cmake build directory (cmake mode only)
    "out_dir": ".out/anvil_build/myproj", // where to collect artifacts
    "cmake_target": "my_target",  // cmake --build --target (cmake mode only)
    "cmake_args": [],             // extra cmake configure args
    "env_setup": "",              // script to source before building (optional)
    "include_dirs": [],           // extra -I paths (direct mode)
    "link_flags": "",             // extra linker flags

    "jobs": 0,                    // compile jobs per variant (0 = nproc)
    "parallel_variants": 1,       // how many variants to build simultaneously
    "stop_on_error": false,       // abort on first variant failure
    "clean": false,               // default clean behavior
    "verbose": false              // print full commands
  }

Variant format (with optional compiler/standard):
  {
    "name": "o3_clang",
    "compiler": "clang++",
    "standard": "c++23",
    "cxx_flags": "-O3",
    "defines": []
  }

Usage examples:
  # Single file, auto-detected or default variants
  python -m anvil --target sandbox/test.cpp

  # Folder (all .cpp files recursively)
  python -m anvil --target sandbox/Filters/

  # Explicit configs (CMake mode)
  python -m anvil \
    --project-config myproject/anvil.project.json \
    --variants myproject/anvil.variants.quick.json \
    --build-type Release --clean

  # Use a preset name to pick anvil.variants.<preset>.json
  python -m anvil --target src/ --preset full
"""

import argparse
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path


# =============================================================================
# Data classes
# =============================================================================

@dataclass(frozen=True)
class BuildVariant:
    name: str
    compiler: str
    standard: str
    cxx_flags: str
    defines: tuple[str, ...]


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    build_dir: str
    out_dir: str
    cmake_target: str
    cmake_args: tuple[str, ...]
    env_setup: str
    include_dirs: tuple[str, ...]
    link_flags: str
    # Build behavior
    jobs: int            # 0 = auto (nproc)
    parallel_variants: int
    stop_on_error: bool
    clean: bool
    verbose: bool


# =============================================================================
# Defaults
# =============================================================================

DEFAULT_COMPILER = "g++"
DEFAULT_STANDARD = "c++23"

DEFAULT_VARIANTS_DATA: list[dict] = [
    {"name": "o2_baseline", "cxx_flags": "-O2", "defines": []},
    {"name": "o3_baseline", "cxx_flags": "-O3", "defines": []},
    {"name": "ofast_fastmath", "cxx_flags": "-Ofast -ffast-math", "defines": []},
]

DEFAULT_PROJECT_CONFIG = ProjectConfig(
    name="",
    build_dir="/build/anvil",
    out_dir="",
    cmake_target="",
    cmake_args=(),
    env_setup="",
    include_dirs=(),
    link_flags="",
    jobs=0,
    parallel_variants=1,
    stop_on_error=False,
    clean=False,
    verbose=False,
)


# =============================================================================
# Utilities
# =============================================================================

def effective_jobs(jobs: int) -> int:
    if jobs <= 0:
        return multiprocessing.cpu_count() or 1
    return jobs


def sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def run_cmd(command: list[str], env: dict | None = None, verbose: bool = False) -> None:
    if verbose:
        print(f"    $ {' '.join(command)}")
    merged_env = {**os.environ, **(env or {})}
    proc = subprocess.run(command, env=merged_env)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {' '.join(command)}")


def run_bash(command: str, verbose: bool = False) -> None:
    if verbose:
        print(f"    $ {command[:200]}")
    proc = subprocess.run(["bash", "-lc", command], text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {command}")


def find_sources(target_dir: Path) -> list[Path]:
    """Find all C/C++ source files recursively under target_dir."""
    extensions = {".cpp", ".cxx", ".cc", ".c"}
    sources = []
    for ext in extensions:
        sources.extend(target_dir.rglob(f"*{ext}"))
    return sorted(sources)


def resolve_compiler_command(compiler: str) -> list[str]:
    """Convert a compiler string to a command list (handles 'zig c++' etc.)."""
    return compiler.split()


# =============================================================================
# Config discovery & parsing
# =============================================================================

def discover_configs(target_path: Path, preset: str) -> tuple[Path | None, Path | None]:
    """Look for anvil.project.json and anvil.variants.<preset>.json near the target."""
    search_dir = target_path.parent if target_path.is_file() else target_path

    project_json = search_dir / "anvil.project.json"
    variants_json = search_dir / f"anvil.variants.{preset}.json"

    proj = project_json if project_json.exists() else None
    var = variants_json if variants_json.exists() else None
    return proj, var


def parse_project_config(path: Path) -> ProjectConfig:
    data = json.loads(path.read_text(encoding="utf-8"))

    name = str(data.get("name", path.parent.name)).strip()
    build_dir = str(data.get("build_dir", f"/build/anvil/{name}")).strip()
    out_dir = str(data.get("out_dir", f".out/anvil_build/{name}")).strip()

    cmake_target = str(data.get("cmake_target", "")).strip()
    cmake_args_raw = data.get("cmake_args", [])
    if not isinstance(cmake_args_raw, list):
        raise ValueError("'cmake_args' must be a list")
    cmake_args = tuple(str(v) for v in cmake_args_raw)

    env_setup = str(data.get("env_setup", "")).strip()

    include_dirs_raw = data.get("include_dirs", [])
    if not isinstance(include_dirs_raw, list):
        raise ValueError("'include_dirs' must be a list")
    include_dirs = tuple(str(d).strip() for d in include_dirs_raw)
    link_flags = str(data.get("link_flags", "")).strip()

    jobs = int(data.get("jobs", 0))
    parallel_variants = max(1, int(data.get("parallel_variants", 1)))
    stop_on_error = bool(data.get("stop_on_error", False))
    clean = bool(data.get("clean", False))
    verbose = bool(data.get("verbose", False))

    return ProjectConfig(
        name=name,
        build_dir=build_dir,
        out_dir=out_dir,
        cmake_target=cmake_target,
        cmake_args=cmake_args,
        env_setup=env_setup,
        include_dirs=include_dirs,
        link_flags=link_flags,
        jobs=jobs,
        parallel_variants=parallel_variants,
        stop_on_error=stop_on_error,
        clean=clean,
        verbose=verbose,
    )


def parse_variants(path: Path) -> list[BuildVariant]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Variants JSON must be a list")
    return _parse_variants_list(data, source=str(path))


def _parse_variants_list(data: list, source: str = "<builtin>") -> list[BuildVariant]:
    variants: list[BuildVariant] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Variant entry {i} in {source} must be an object")

        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"Variant entry {i} in {source} missing non-empty 'name'")

        compiler = str(item.get("compiler", DEFAULT_COMPILER)).strip()
        standard = str(item.get("standard", DEFAULT_STANDARD)).strip()
        cxx_flags = str(item.get("cxx_flags", "")).strip()
        defines_raw = item.get("defines", [])
        if not isinstance(defines_raw, list):
            raise ValueError(f"Variant '{name}' key 'defines' must be a list")

        defines = tuple(str(d).strip() for d in defines_raw if str(d).strip())
        variants.append(BuildVariant(
            name=name, compiler=compiler, standard=standard,
            cxx_flags=cxx_flags, defines=defines,
        ))

    return variants


def default_variants() -> list[BuildVariant]:
    return _parse_variants_list(DEFAULT_VARIANTS_DATA)


# =============================================================================
# Build: compose flags
# =============================================================================

def compose_effective_flags(cxx_flags: str, defines: tuple[str, ...]) -> str:
    define_flags = " ".join(f"-D{d}" for d in defines)
    parts = [p for p in [cxx_flags.strip(), define_flags.strip()] if p]
    return " ".join(parts)


# =============================================================================
# Build mode: Direct compilation (single file or folder, no CMake)
# =============================================================================

def build_direct(
    sources: list[Path],
    include_dir: Path,
    out_dir: Path,
    output_name: str,
    variant: BuildVariant,
    config: ProjectConfig,
    extra_args: list[str] | None = None,
) -> dict:
    """Compile source files directly (no CMake)."""
    out_bin = out_dir / f"{output_name}__{variant.name}"

    compiler_cmd = resolve_compiler_command(variant.compiler)
    effective_flags = compose_effective_flags(variant.cxx_flags, variant.defines)

    cmd = [*compiler_cmd]
    if variant.standard:
        cmd.append(f"-std={variant.standard}")

    if effective_flags:
        cmd.extend(effective_flags.split())

    cmd.extend(["-fdiagnostics-color=always", "-g"])

    # Include dirs: source dir + extras from project config
    cmd.append(f"-I{include_dir}")
    for inc in config.include_dirs:
        cmd.append(f"-I{inc}")

    cmd.extend(str(s) for s in sources)
    cmd.extend(["-o", str(out_bin)])

    # Link flags from config
    if config.link_flags:
        cmd.extend(config.link_flags.split())

    if extra_args:
        cmd.extend(extra_args)

    run_cmd(cmd, verbose=config.verbose)

    metadata = {
        "name": variant.name,
        "compiler": variant.compiler,
        "standard": variant.standard,
        "cxx_flags": variant.cxx_flags,
        "defines": list(variant.defines),
        "effective_flags": effective_flags,
        "sources": [str(s) for s in sources],
        "artifact": str(out_bin),
    }

    (out_dir / f"{output_name}__{variant.name}.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


# =============================================================================
# Build mode: CMake
# =============================================================================

def build_cmake(
    root: Path,
    config: ProjectConfig,
    out_dir: Path,
    variant: BuildVariant,
    build_type: str,
) -> dict:
    """Build a CMake target for a single variant."""
    build_dir = Path(config.build_dir) / variant.name / build_type.lower()
    if config.clean and build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    effective_flags = compose_effective_flags(variant.cxx_flags, variant.defines)
    jobs = effective_jobs(config.jobs)

    # Compiler override
    compiler_override = ""
    if variant.compiler and variant.compiler != DEFAULT_COMPILER:
        compiler_override = f"-DCMAKE_CXX_COMPILER={sh_quote(variant.compiler)} "

    cmake_args_joined = " ".join(sh_quote(arg) for arg in config.cmake_args)

    cmake_cmd = (
        f"cmake -S {sh_quote(str(root))} -B {sh_quote(str(build_dir))} "
        f"{compiler_override}"
        f"{cmake_args_joined} "
        f"-DCMAKE_BUILD_TYPE={sh_quote(build_type)}"
    )

    # Inject flags via CXXFLAGS env var
    if config.env_setup:
        cmake_config = (
            f"source {sh_quote(config.env_setup)} && "
            f"export CXXFLAGS=\"$CXXFLAGS {effective_flags}\" && "
            f"{cmake_cmd}"
        )
        cmake_build = (
            f"source {sh_quote(config.env_setup)} && "
            f"cmake --build {sh_quote(str(build_dir))} --parallel {jobs}"
            f" --target {sh_quote(config.cmake_target)}"
        )
    else:
        cmake_config = f"export CXXFLAGS=\"$CXXFLAGS {effective_flags}\" && {cmake_cmd}"
        cmake_build = (
            f"cmake --build {sh_quote(str(build_dir))} --parallel {jobs}"
            f" --target {sh_quote(config.cmake_target)}"
        )

    run_bash(cmake_config, verbose=config.verbose)
    run_bash(cmake_build, verbose=config.verbose)

    # Find artifact in build tree
    out_bin = out_dir / f"{config.cmake_target}__{variant.name}"
    built_bin = _find_cmake_artifact(build_dir, config.cmake_target)
    if built_bin:
        shutil.copy2(built_bin, out_bin)
    else:
        raise FileNotFoundError(
            f"Could not locate artifact for target '{config.cmake_target}' in {build_dir}"
        )

    metadata = {
        "project": config.name,
        "name": variant.name,
        "compiler": variant.compiler,
        "standard": variant.standard,
        "build_type": build_type,
        "cxx_flags": variant.cxx_flags,
        "defines": list(variant.defines),
        "effective_flags": effective_flags,
        "build_dir": str(build_dir),
        "artifact": str(out_bin),
    }

    (out_dir / f"{config.cmake_target}__{variant.name}.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


def _find_cmake_artifact(build_dir: Path, target_name: str) -> Path | None:
    """Heuristic: find the built binary by target name in the build tree."""
    for candidate in build_dir.rglob(target_name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    for ext in ("", ".extra", ".exe"):
        for candidate in build_dir.rglob(f"{target_name}{ext}"):
            if candidate.is_file():
                return candidate
    return None


# =============================================================================
# Mode detection
# =============================================================================

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


# =============================================================================
# Orchestration
# =============================================================================

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

    if config.parallel_variants > 1:
        with ProcessPoolExecutor(max_workers=config.parallel_variants) as executor:
            futures = {}
            for variant in variants:
                fut = executor.submit(
                    build_direct, sources, include_dir, out_dir,
                    output_name, variant, config, extra_args or None,
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
                    if config.stop_on_error:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
    else:
        for variant in variants:
            print(f"\n=== [{variant.compiler} -std={variant.standard}] {variant.name} ===")
            try:
                metadata = build_direct(
                    sources=sources, include_dir=include_dir, out_dir=out_dir,
                    output_name=output_name, variant=variant, config=config,
                    extra_args=extra_args or None,
                )
                summary.append(metadata)
                print(f"    -> {metadata['artifact']}")
            except RuntimeError as e:
                had_failure = True
                print(f"    FAILED: {e}", file=sys.stderr)
                summary.append({"name": variant.name, "error": str(e)})
                if config.stop_on_error:
                    break

    _write_summary(out_dir, summary)
    return 1 if (had_failure and config.stop_on_error) else 0


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

    for variant in variants:
        print(f"\n=== [{variant.compiler}] {variant.name} ===")
        try:
            metadata = build_cmake(
                root=root, config=config, out_dir=out_dir,
                variant=variant, build_type=build_type,
            )
            summary.append(metadata)
            print(f"    -> {metadata['artifact']}")
        except (RuntimeError, FileNotFoundError) as e:
            had_failure = True
            print(f"    FAILED: {e}", file=sys.stderr)
            summary.append({"name": variant.name, "error": str(e)})
            if config.stop_on_error:
                break

    _write_summary(out_dir, summary)
    return 1 if (had_failure and config.stop_on_error) else 0


def _write_summary(out_dir: Path, summary: list[dict]) -> None:
    summary_path = out_dir / "build_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    succeeded = sum(1 for s in summary if "error" not in s)
    failed = len(summary) - succeeded
    print(f"\nDone: {succeeded} succeeded, {failed} failed.")
    print(f"Artifacts: {out_dir}")
    print(f"Summary:   {summary_path}")


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Anvil, C/C++ build-matrix tool: compiles C/C++ targets with multiple variant configurations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target", type=Path,
        help="Path to a .cpp file or folder. Auto-detects build mode (file/folder/cmake).",
    )
    parser.add_argument(
        "--project-config", type=Path,
        help="Explicit project JSON config path. Overrides auto-detection.",
    )
    parser.add_argument(
        "--variants", type=Path,
        help="Explicit variants JSON path. Overrides auto-detection.",
    )
    parser.add_argument(
        "--preset", default="quick",
        help="Variant preset name — looks for anvil.variants.<preset>.json (default: quick).",
    )
    parser.add_argument(
        "--build-type", default="Release",
        choices=["Release", "Debug", "MinSizeRel", "RelWithDebInfo"],
        help="CMake build type (cmake mode only).",
    )
    parser.add_argument(
        "--clean", action="store_true", default=None,
        help="Clean build dirs before building (overrides config).",
    )
    parser.add_argument(
        "--stop-on-error", action="store_true", default=None,
        help="Stop on first variant failure (overrides config).",
    )
    parser.add_argument(
        "--jobs", "-j", type=int, default=None,
        help="Compile jobs per variant (0 = nproc, overrides config).",
    )
    parser.add_argument(
        "--parallel", "-p", type=int, default=None,
        help="Variants to build in parallel (overrides config).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=None,
        help="Print full compilation commands.",
    )
    parser.add_argument(
        "--extra-args", nargs="*", default=[],
        help="Extra compiler/linker arguments (direct mode only).",
    )
    args = parser.parse_args()

    root = Path(os.getcwd())

    # --- Resolve target ---
    if args.target is None and args.project_config is None:
        parser.error("Provide --target or --project-config")

    if args.target:
        target = args.target.resolve()
        if not target.exists():
            print(f"Target not found: {target}", file=sys.stderr)
            return 2
    else:
        target = args.project_config.parent.resolve()

    # Discover config files near target
    proj_json, var_json = discover_configs(target, args.preset)
    if args.project_config and args.project_config.exists():
        proj_json = args.project_config
    if args.variants and args.variants.exists():
        var_json = args.variants

    # Parse project config (or use defaults)
    if proj_json:
        print(f"Config:   {proj_json}")
        config = parse_project_config(proj_json)
    else:
        config = DEFAULT_PROJECT_CONFIG

    # Apply CLI overrides
    overrides: dict = {}
    if args.clean is not None:
        overrides["clean"] = args.clean
    if args.stop_on_error is not None:
        overrides["stop_on_error"] = args.stop_on_error
    if args.jobs is not None:
        overrides["jobs"] = args.jobs
    if args.parallel is not None:
        overrides["parallel_variants"] = max(1, args.parallel)
    if args.verbose is not None:
        overrides["verbose"] = args.verbose
    if not config.name:
        overrides["name"] = target.stem if target.is_file() else target.name
    if overrides:
        config = replace(config, **overrides)

    # Parse variants
    if var_json:
        print(f"Variants: {var_json}")
        variants = parse_variants(var_json)
    else:
        print("Variants: built-in defaults")
        variants = default_variants()

    if not variants:
        print("No variants defined.", file=sys.stderr)
        return 2

    # Determine mode
    mode = detect_mode(target) if args.target else "cmake"

    # Resolve output directory
    if config.out_dir:
        out_path = Path(config.out_dir)
        out_dir = out_path if out_path.is_absolute() else root / out_path
    else:
        out_dir = root / ".out" / "anvil_build" / config.name
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- CMake mode ---
    if mode == "cmake":
        if not config.cmake_target:
            print("CMake mode requires 'cmake_target' in project config.", file=sys.stderr)
            return 2
        return _run_cmake_matrix(target, config, out_dir, variants, args.build_type)

    # --- Direct compilation mode (file or folder) ---
    if mode == "file":
        sources = [target]
        include_dir = target.parent
        output_name = target.stem
    else:
        sources = find_sources(target)
        if not sources:
            print(f"No source files found under: {target}", file=sys.stderr)
            return 2
        include_dir = target
        output_name = target.name

    print(f"Mode:    {mode}")
    print(f"Sources: {len(sources)} file(s)")
    print(f"Output:  {out_dir}")
    if config.parallel_variants > 1:
        print(f"Parallel: {config.parallel_variants} variants")

    return _run_direct_matrix(sources, include_dir, out_dir, output_name, variants, config, args.extra_args)


if __name__ == "__main__":
    raise SystemExit(main())
