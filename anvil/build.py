import json
import os
import re
import shutil
from pathlib import Path

from .models import BuildVariant, ProjectConfig
from .utils import effective_jobs, resolve_compiler_command, run_bash, run_cmd, sh_quote


ANSI_CYAN = "\033[1;36m"
ANSI_RESET = "\033[0m"


def _anvil_log(message: str) -> None:
    print(f"{ANSI_CYAN}========== ANVIL =========={ANSI_RESET}")
    print(f"{ANSI_CYAN}{message}{ANSI_RESET}")
    print(f"{ANSI_CYAN}==========================={ANSI_RESET}")


def compose_effective_flags(cxx_flags: tuple[str, ...], defines: tuple[str, ...]) -> str:
    flags = " ".join(cxx_flags)
    define_flags = " ".join(f"-D{d}" for d in defines)
    parts = [p for p in [flags.strip(), define_flags.strip()] if p]
    return " ".join(parts)


def _cmake_standard_arguments(standard: str) -> list[str]:
    match = re.fullmatch(r"(c\+\+|gnu\+\+)(\d+)", standard)
    if match is None:
        raise ValueError(f"Unsupported C++ standard for CMake: {standard!r}")
    return [
        f"-DCMAKE_CXX_STANDARD={match.group(2)}",
        "-DCMAKE_CXX_STANDARD_REQUIRED=ON",
        f"-DCMAKE_CXX_EXTENSIONS={'ON' if match.group(1) == 'gnu++' else 'OFF'}",
    ]


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

    compiler = variant.cxx_compiler or variant.compiler
    compiler_cmd = resolve_compiler_command(compiler)
    effective_defines = variant.defines + variant.cxx_defines
    effective_flags = compose_effective_flags(variant.cxx_flags, effective_defines)

    cmd = [*compiler_cmd]
    if variant.standard:
        cmd.append(f"-std={variant.standard}")

    cmd.extend(variant.cxx_flags)
    cmd.extend(f"-D{d}" for d in effective_defines)

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
        "compiler": compiler,
        "standard": variant.standard,
        "cxx_flags": list(variant.cxx_flags),
        "defines": list(variant.defines),
        "cxx_defines": list(variant.cxx_defines),
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

    effective_c_flags = compose_effective_flags(variant.c_flags, variant.defines + variant.c_defines)
    effective_cxx_flags = compose_effective_flags(
        variant.cxx_flags, variant.defines + variant.cxx_defines
    )
    jobs = effective_jobs(config.jobs)
    variant_defaults = BuildVariant()
    cxx_compiler = variant.cxx_compiler or variant.compiler

    cmake_config_cmd = ["cmake", "-S", str(root), "-B", str(build_dir)]
    if cxx_compiler and cxx_compiler != variant_defaults.compiler:
        cmake_config_cmd.append(f"-DCMAKE_CXX_COMPILER={cxx_compiler}")
    if variant.c_compiler:
        cmake_config_cmd.append(f"-DCMAKE_C_COMPILER={variant.c_compiler}")
    if variant.standard:
        cmake_config_cmd.extend(_cmake_standard_arguments(variant.standard))

    cmake_config_cmd.extend(config.cmake_args)

    selected_config = config.cmake_build_type or build_type
    if selected_config:
        cmake_config_cmd.append(f"-DCMAKE_BUILD_TYPE={selected_config}")

    config_name_upper = selected_config.upper()

    cmake_build_cmd = [
        "cmake",
        "--build",
        str(build_dir),
        "--parallel",
        str(jobs),
        "--target",
        config.cmake_target,
    ]
    if selected_config:
        cmake_build_cmd.extend(["--config", selected_config])

    def _run_configure(args: list[str]) -> None:
        if config.env_setup:
            configure_cmd = " ".join(sh_quote(token) for token in args)
            run_bash(f"source {sh_quote(config.env_setup)} && {configure_cmd}", verbose=config.verbose)
        else:
            run_cmd(args, verbose=config.verbose)

    is_standard_config = config_name_upper in {"DEBUG", "RELEASE", "RELWITHDEBINFO", "MINSIZEREL"}
    cxx_key = f"CMAKE_CXX_FLAGS_{config_name_upper}"
    c_key = f"CMAKE_C_FLAGS_{config_name_upper}"

    if is_standard_config:
        _anvil_log(f"Standard config '{selected_config}': running preliminary configure to gather CMake defaults")
        _run_configure(cmake_config_cmd)

        cache_file = build_dir / "CMakeCache.txt"
        existing_cxx_flags = _read_cmake_cache_value(cache_file, cxx_key)

        merged_cxx_flags = _merge_flag_strings(existing_cxx_flags, effective_cxx_flags)

        _anvil_log(f"Injecting merged flags into {cxx_key}")
        second_configure_cmd = [*cmake_config_cmd]
        second_configure_cmd.append(f"-D{cxx_key}:STRING={merged_cxx_flags}")
        if effective_c_flags:
            existing_c_flags = _read_cmake_cache_value(cache_file, c_key)
            merged_c_flags = _merge_flag_strings(existing_c_flags, effective_c_flags)
            second_configure_cmd.append(f"-D{c_key}:STRING={merged_c_flags}")
        _run_configure(second_configure_cmd)
    else:
        _anvil_log(f"Custom config '{selected_config}': injecting blank-state Anvil flags")
        merged_cxx_flags = effective_cxx_flags

        single_configure_cmd = [*cmake_config_cmd]
        single_configure_cmd.append(f"-D{cxx_key}:STRING={merged_cxx_flags}")
        if effective_c_flags:
            merged_c_flags = effective_c_flags
            single_configure_cmd.append(f"-D{c_key}:STRING={merged_c_flags}")
        _run_configure(single_configure_cmd)

    if config.env_setup:
        cmake_build = " ".join(sh_quote(token) for token in cmake_build_cmd)
        _anvil_log(f"Building target '{config.cmake_target}' with config '{selected_config}'")
        run_bash(f"source {sh_quote(config.env_setup)} && {cmake_build}", verbose=config.verbose)
    else:
        _anvil_log(f"Building target '{config.cmake_target}' with config '{selected_config}'")
        run_cmd(cmake_build_cmd, verbose=config.verbose)

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
        "compiler": cxx_compiler,
        "c_compiler": variant.c_compiler,
        "cxx_compiler": cxx_compiler,
        "standard": variant.standard,
        "build_type": build_type,
        "cmake_build_type": selected_config,
        "c_flags": list(variant.c_flags),
        "cxx_flags": list(variant.cxx_flags),
        "defines": list(variant.defines),
        "c_defines": list(variant.c_defines),
        "cxx_defines": list(variant.cxx_defines),
        "effective_c_flags": effective_c_flags,
        "effective_cxx_flags": effective_cxx_flags,
        "effective_flags": effective_cxx_flags,
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


def _read_cmake_cache_value(cache_file: Path, key: str) -> str:
    if not cache_file.exists():
        return ""

    prefix = f"{key}:"
    for line in cache_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(prefix):
            _, _, value = line.partition("=")
            return value.strip()
    return ""


def _merge_flag_strings(existing: str, injected: str) -> str:
    parts = [p.strip() for p in (existing, injected) if p and p.strip()]
    return " ".join(parts)


