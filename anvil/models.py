from dataclasses import dataclass


@dataclass(frozen=True)
class BuildVariant:
    name: str = ""
    compiler: str = "g++"
    standard: str = "c++23"
    cxx_flags: tuple[str, ...] = ()
    defines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectConfig:
    name: str = ""
    build_dir: str = "/build/anvil"
    out_dir: str = ""
    cmake_target: str = ""
    cmake_build_type: str = ""
    cmake_args: tuple[str, ...] = ()
    env_setup: str = ""
    include_dirs: tuple[str, ...] = ()
    link_flags: str = ""
    jobs: int = 0
    parallel_variants: int = 1
    stop_on_error: bool = False
    clean: bool = False
    verbose: bool = False
