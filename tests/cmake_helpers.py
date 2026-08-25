import shutil

import pytest


def require_cmake() -> None:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is required for this test")


def cache_value(cache_text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in cache_text.splitlines():
        if line.startswith(prefix):
            return line.partition("=")[2]
    return ""
