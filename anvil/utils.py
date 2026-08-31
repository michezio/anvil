import multiprocessing
import os
import shlex
import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path.cwd().resolve()


def resolve_path(path_like: str | Path | None, *, base_dir: Path | None = None) -> Path | None:
    if path_like is None:
        return None
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve(strict=False)
    base = base_dir if base_dir is not None else Path.cwd()
    return (base / path).resolve(strict=False)


def resolve_existing_path(
    path_like: str | Path | None,
    *,
    base_dir: Path | None = None,
    fallback_dirs: tuple[Path, ...] = (),
) -> Path | None:
    if path_like is None:
        return None

    path = Path(path_like).expanduser()
    if path.is_absolute():
        candidate = path.resolve(strict=False)
        return candidate if candidate.exists() else None

    search_dirs = [base_dir if base_dir is not None else Path.cwd(), *fallback_dirs]
    for search_dir in search_dirs:
        candidate = (search_dir / path).resolve(strict=False)
        if candidate.exists():
            return candidate

    return None


def resolve_config_path(
    path_like: str | Path | None,
    *,
    base_dir: Path | None = None,
    fallback_dirs: tuple[Path, ...] = (),
    names: tuple[str, ...] = (),
) -> Path | None:
    if path_like is None:
        return None

    explicit_path = resolve_existing_path(path_like, base_dir=base_dir, fallback_dirs=fallback_dirs)
    if explicit_path is not None:
        if explicit_path.is_file():
            return explicit_path
        if explicit_path.is_dir():
            for name in names:
                candidate = explicit_path / name
                if candidate.exists():
                    return candidate
        return None

    return None


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
    return shlex.split(compiler)
