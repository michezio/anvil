from dataclasses import dataclass


@dataclass(frozen=True)
class BuildVariant:
    name: str = ""
    compiler: str = "g++"
    c_compiler: str = ""
    cxx_compiler: str = ""
    standard: str = "c++23"
    c_flags: tuple[str, ...] = ()
    cxx_flags: tuple[str, ...] = ()
    defines: tuple[str, ...] = ()
    c_defines: tuple[str, ...] = ()
    cxx_defines: tuple[str, ...] = ()
    allow_failure: bool = False


@dataclass(frozen=True)
class ProjectConfig:
    name: str = ""
    build_dir: str = "/build/anvil"
    out_dir: str = ""
    cmake_source_dir: str = ""
    cmake_target: str = ""
    cmake_build_type: str = ""
    cmake_toolchain_file: str = ""
    cmake_artifact: str = ""
    cmake_args: tuple[str, ...] = ()
    env_setup: str = ""
    include_dirs: tuple[str, ...] = ()
    link_flags: str = ""
    jobs: int = 0
    parallel_variants: int = 1
    stop_on_error: bool = False
    resume: bool = False
    clean: bool = False
    verbose: bool = False
