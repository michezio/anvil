import shutil
from pathlib import Path

import pytest


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        pytest.skip(f"{name} is required for this test")


@pytest.fixture
def available_compiler() -> str:
    for compiler in ("g++", "clang++", "c++"):
        if shutil.which(compiler) is not None:
            return compiler
    pytest.skip("A C++ compiler is required (tried: g++, clang++, c++)")
    raise AssertionError("unreachable")


@pytest.fixture
def cmake_flags_asset_root() -> Path:
    return Path(__file__).parent / "assets" / "cmake_flags_project"


def resolve_artifact_path(artifact_path: Path) -> Path:
    """Return the produced artifact path, accounting for Windows .exe outputs."""
    if artifact_path.exists():
        return artifact_path

    exe_candidate = artifact_path.with_suffix(".exe")
    if exe_candidate.exists():
        return exe_candidate

    return artifact_path
