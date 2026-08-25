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
