import json
import os
import shutil
from pathlib import Path

from .models import BuildVariant, ProjectConfig
from .utils import effective_jobs, resolve_compiler_command, run_bash, run_cmd, sh_quote


def compose_effective_flags(cxx_flags: tuple[str, ...], defines: tuple[str, ...]) -> str:
    flags = " ".join(cxx_flags)
    define_flags = " ".join(f"-D{d}" for d in defines)
    parts = [p for p in [flags.strip(), define_flags.strip()] if p]
    return " ".join(parts)


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

    cmd.extend(variant.cxx_flags)
    cmd.extend(f"-D{d}" for d in variant.defines)

    cmd.extend(["-fdiagnostics-color=always", "-g"])

    cmd.append(f"-I{include_dir}")
    for inc in config.include_dirs:
        cmd.append(f"-I{inc}")

    cmd.extend(str(s) for s in sources)
    cmd.extend(["-o", str(out_bin)])

    if config.link_flags:
        cmd.extend(config.link_flags.split())

    if extra_args:
        cmd.extend(extra_args)

    run_cmd(cmd, verbose=config.verbose)

    metadata = {
        "name": variant.name,
        "compiler": variant.compiler,
        "standard": variant.standard,
        "cxx_flags": list(variant.cxx_flags),
        "defines": list(variant.defines),
        "effective_flags": effective_flags,
        "sources": [str(s) for s in sources],
        "artifact": str(out_bin),
    }

    (out_dir / f"{output_name}__{variant.name}.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


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
    variant_defaults = BuildVariant()

    compiler_override = ""
    if variant.compiler and variant.compiler != variant_defaults.compiler:
        compiler_override = f"-DCMAKE_CXX_COMPILER={sh_quote(variant.compiler)} "

    cmake_args_joined = " ".join(sh_quote(arg) for arg in config.cmake_args)

    cmake_cmd = (
        f"cmake -S {sh_quote(str(root))} -B {sh_quote(str(build_dir))} "
        f"{compiler_override}"
        f"{cmake_args_joined}"
    )
    if config.cmake_build_type:
        cmake_cmd = f"{cmake_cmd} -DCMAKE_BUILD_TYPE={sh_quote(config.cmake_build_type)}"

    config_name_upper = (config.cmake_build_type or build_type).upper()
    cmake_config = (
        f"{cmake_cmd} "
        f"-DCMAKE_CXX_FLAGS_{config_name_upper}:STRING={sh_quote(effective_flags)} "
        #f"-DCMAKE_C_FLAGS_{config_name_upper}:STRING={sh_quote(effective_flags)}"
    )
    cmake_build = (
        f"cmake --build {sh_quote(str(build_dir))} --parallel {jobs}"
        f" --target {sh_quote(config.cmake_target)}"
    )

    if config.env_setup:
        cmake_config = f"source {sh_quote(config.env_setup)} && {cmake_config}"
        cmake_build = f"source {sh_quote(config.env_setup)} && {cmake_build}"

    run_bash(cmake_config, verbose=config.verbose)
    run_bash(cmake_build, verbose=config.verbose)

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
        "cxx_flags": list(variant.cxx_flags),
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


