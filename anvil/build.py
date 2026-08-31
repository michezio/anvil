import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
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
    fingerprint: str = "",
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
        cmd.extend(shlex.split(config.link_flags))

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
        "artifact_sha256": _file_sha256(out_bin),
        "fingerprint": fingerprint,
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
    fingerprint: str = "",
) -> dict:
    """Build a CMake target for a single variant."""
    build_dir = Path(config.build_dir) / variant.name / build_type.lower()
    if config.clean and build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    file_api_query = build_dir / ".cmake" / "api" / "v1" / "query" / "codemodel-v2"
    file_api_query.parent.mkdir(parents=True, exist_ok=True)
    file_api_query.touch()

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
    if config.cmake_toolchain_file:
        cmake_config_cmd.append(f"-DCMAKE_TOOLCHAIN_FILE={config.cmake_toolchain_file}")
    cmake_config_cmd.append("-DCMAKE_EXPORT_COMPILE_COMMANDS=ON")

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
    built_bin = _find_cmake_artifact(
        build_dir,
        config.cmake_target,
        selected_config=selected_config,
        explicit_artifact=config.cmake_artifact,
    )
    if built_bin:
        shutil.copy2(built_bin, out_bin)
    else:
        raise FileNotFoundError(
            f"Could not locate artifact for target '{config.cmake_target}' in {build_dir}"
        )

    compile_commands = build_dir / "compile_commands.json"
    copied_compile_commands = out_dir / f"{config.cmake_target}__{variant.name}.compile_commands.json"
    if compile_commands.exists():
        shutil.copy2(compile_commands, copied_compile_commands)

    cache_file = build_dir / "CMakeCache.txt"
    resolved_cxx_compiler = _read_cmake_cache_value(cache_file, "CMAKE_CXX_COMPILER")
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
        "source_root": str(root.resolve(strict=False)),
        "cmake_target": config.cmake_target,
        "cmake_generator": _read_cmake_cache_value(cache_file, "CMAKE_GENERATOR"),
        "cmake_version": _command_version(["cmake", "--version"]),
        "requested_compiler": cxx_compiler,
        "resolved_cxx_compiler": resolved_cxx_compiler,
        "compiler_version": _command_version([resolved_cxx_compiler, "--version"]),
        "toolchain_file": config.cmake_toolchain_file or None,
        "toolchain_sha256": _file_sha256(Path(config.cmake_toolchain_file))
        if config.cmake_toolchain_file
        else None,
        "environment_setup": config.env_setup or None,
        "environment_setup_sha256": _file_sha256(Path(config.env_setup)) if config.env_setup else None,
        "environment": _selected_environment(config.env_setup),
        "artifact_sha256": _file_sha256(out_bin),
        "fingerprint": fingerprint,
        "compile_commands": str(copied_compile_commands) if copied_compile_commands.exists() else None,
        "configure_command": cmake_config_cmd,
        "build_command": cmake_build_cmd,
        "artifact": str(out_bin),
    }

    (out_dir / f"{config.cmake_target}__{variant.name}.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


def _find_cmake_artifact(
    build_dir: Path,
    target_name: str,
    *,
    selected_config: str = "",
    explicit_artifact: str = "",
) -> Path | None:
    if explicit_artifact:
        candidate = Path(explicit_artifact)
        if not candidate.is_absolute():
            candidate = build_dir / candidate
        return candidate if candidate.is_file() else None

    reply_dir = build_dir / ".cmake" / "api" / "v1" / "reply"
    indexes = sorted(reply_dir.glob("index-*.json"), reverse=True)
    if indexes:
        index = json.loads(indexes[0].read_text(encoding="utf-8"))
        codemodel_ref = index.get("reply", {}).get("codemodel-v2")
        if isinstance(codemodel_ref, dict):
            codemodel = json.loads((reply_dir / codemodel_ref["jsonFile"]).read_text(encoding="utf-8"))
            configurations = codemodel.get("configurations", [])
            preferred = [c for c in configurations if c.get("name") == selected_config]
            for configuration in preferred or configurations:
                for target_ref in configuration.get("targets", []):
                    if target_ref.get("name") != target_name:
                        continue
                    target = json.loads((reply_dir / target_ref["jsonFile"]).read_text(encoding="utf-8"))
                    for artifact in target.get("artifacts", []):
                        candidate = build_dir / artifact["path"]
                        if candidate.is_file():
                            return candidate

    # Older CMake versions or unsupported generators may not provide a codemodel reply.
    for candidate in build_dir.rglob(target_name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    for ext in ("", ".extra", ".exe"):
        for candidate in build_dir.rglob(f"{target_name}{ext}"):
            if candidate.is_file():
                return candidate
    return None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command_version(command: list[str]) -> str:
    if not command[0]:
        return ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else ""


def _selected_environment(env_setup: str) -> dict[str, str]:
    names = ("CC", "CXX", "SYSROOT", "SDKTARGETSYSROOT", "TARGET_PREFIX")
    if not env_setup:
        return {name: os.environ[name] for name in names if name in os.environ}
    command = f"source {sh_quote(env_setup)} && env -0"
    result = subprocess.run(["bash", "-lc", command], capture_output=True, check=False)
    if result.returncode != 0:
        return {}
    environment = {}
    for item in result.stdout.split(b"\0"):
        key, separator, value = item.partition(b"=")
        name = key.decode(errors="replace")
        if separator and name in names:
            environment[name] = value.decode(errors="replace")
    return environment


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


