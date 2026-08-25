#!/usr/bin/env python3
"""
Anvil, C/C++ build-matrix tool.

Builds a C/C++ target multiple times with variant-specific compilers, flags,
and defines. Supports three modes:

  1. Single .cpp file   — compiles directly (no CMake).
  2. Folder             — compiles all .cpp/.c files recursively (no CMake).
  3. CMake project      — uses CMakeLists.txt if present in target directory.

Config discovery:
  - If anvil_project.json and anvil_variants.json exist next to the project
    definition path, they are used. The default project path is the target,
    and the default variants path is the project directory.
  - Otherwise built-in defaults are applied.

anvil_project.json format:
  {
    "name": "my_project",
    "build_dir": "/build/myproj",
    "out_dir": ".out/anvil_build/myproj",
    "cmake": {
      "target": "my_target",
      "build_type": "Release",
      "args": []
    },
    "env_setup": "",
    "include_dirs": [],
    "link_flags": "",
    "jobs": 0,
    "parallel_variants": 1,
    "stop_on_error": false,
    "clean": false,
    "verbose": false
  }

Variant format (with optional compiler/standard):
  {
    "name": "o3_clang",
    "compiler": "clang++",
    "standard": "c++23",
        "cxx_flags": ["-O3"],
    "defines": []
  }

Usage examples:
  # Single file, auto-detected or default variants
  python -m anvil --target sandbox/test.cpp

  # Folder (all .cpp files recursively)
  python -m anvil --target sandbox/Filters/

  # Use a project definition from another location while building the cwd project
  python -m anvil --project extras/Eigen_benchmark
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .config import default_variants, parse_project_config, parse_variants
from .models import ProjectConfig
from .orchestrator import _run_cmake_matrix, _run_direct_matrix, detect_mode
from .utils import (
    find_sources,
    repo_root,
    resolve_config_path,
    resolve_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Anvil, C/C++ build-matrix tool: compiles C/C++ targets with multiple variant configurations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
        + "\nPath resolution notes:\n- Relative paths are resolved from the current working directory.\n- --project defaults to the target path and resolves to <target>/anvil_project.json.\n- --variants defaults to the project directory and resolves to <project_dir>/anvil_variants.json.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=".",
        help="Path to a .cpp file, folder, or CMake project root. Relative paths are resolved from the current working directory (default: .).",
    )
    parser.add_argument(
        "--project",
        "--project-config",
        "--project-conf",
        type=Path,
        dest="project",
        help="Path to an anvil_project.json file or a folder that contains it. Relative paths are resolved from the current working directory.",
    )
    parser.add_argument(
        "--variants",
        type=Path,
        help="Path to an anvil_variants.json file or a folder that contains it. Relative paths are resolved from the current working directory.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=None,
        help="Clean build dirs before building (overrides config).",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        default=None,
        help="Stop on first variant failure (overrides config).",
    )
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=None,
        help="Compile jobs per variant (0 = nproc, overrides config).",
    )
    parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        default=None,
        help="Variants to build in parallel (overrides config).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=None,
        help="Print full compilation commands.",
    )
    parser.add_argument(
        "--extra-args",
        nargs="*",
        default=[],
        help="Extra compiler/linker arguments (direct mode only).",
    )
    args = parser.parse_args()

    cwd = Path.cwd().resolve()
    root = repo_root()

    target = resolve_path(args.target, base_dir=cwd)
    if target is None or not target.exists():
        print(f"Target not found: {target}", file=sys.stderr)
        return 2

    explicit_proj = None
    if args.project is not None:
        explicit_proj = resolve_config_path(
            args.project,
            base_dir=cwd,
            fallback_dirs=(cwd, target.parent),
            names=("anvil_project.json", "anvil.project.json"),
        )
        if explicit_proj is None:
            print(f"Project config not found: {args.project}", file=sys.stderr)
            return 2

    project_base = target
    if explicit_proj is not None:
        project_base = explicit_proj.parent
    elif args.project is not None:
        project_base = resolve_path(args.project, base_dir=cwd) or target

    explicit_vars = None
    if args.variants is not None:
        explicit_vars = resolve_config_path(
            args.variants,
            base_dir=cwd,
            fallback_dirs=(cwd, project_base, target.parent),
            names=("anvil_variants.json", "anvil.variants.json"),
        )
        if explicit_vars is None:
            print(f"Variants config not found: {args.variants}", file=sys.stderr)
            return 2

    if explicit_proj is None:
        proj_json = resolve_config_path(
            project_base,
            base_dir=cwd,
            fallback_dirs=(cwd, target.parent),
            names=("anvil_project.json", "anvil.project.json"),
        )
    else:
        proj_json = explicit_proj

    if explicit_vars is None:
        var_json = resolve_config_path(
            project_base,
            base_dir=cwd,
            fallback_dirs=(cwd, target.parent),
            names=("anvil_variants.json", "anvil.variants.json"),
        )
    else:
        var_json = explicit_vars

    if proj_json:
        print(f"Config:   {proj_json}")
        config = parse_project_config(proj_json)
    else:
        config = ProjectConfig()

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

    if var_json:
        print(f"Variants: {var_json}")
        variants = parse_variants(var_json)
    else:
        print("Variants: built-in defaults")
        variants = default_variants()

    if not variants:
        print("No variants defined.", file=sys.stderr)
        return 2

    mode = detect_mode(target) if args.target else "cmake"

    if config.out_dir:
        out_path = Path(config.out_dir).expanduser()
        out_dir = out_path if out_path.is_absolute() else (root / out_path)
    else:
        out_dir = root / ".out" / "anvil_build" / config.name
    out_dir = out_dir.resolve(strict=False)
    out_dir.mkdir(parents=True, exist_ok=True)

    if mode == "cmake":
        if not config.cmake_target:
            print("CMake mode requires a cmake.target entry in the project config.", file=sys.stderr)
            return 2
        cmake_root = target.resolve(strict=False)
        return _run_cmake_matrix(cmake_root, config, out_dir, variants, config.cmake_build_type or "Release")

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
    print(f"Target:  {target}")
    print(f"Sources: {len(sources)} file(s)")
    print(f"Output:  {out_dir}")
    if config.parallel_variants > 1:
        print(f"Parallel: {config.parallel_variants} variants")

    return _run_direct_matrix(sources, include_dir, out_dir, output_name, variants, config, args.extra_args)
