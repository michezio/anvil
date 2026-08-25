from pathlib import Path

import pytest

from anvil.build import build_cmake
from anvil.models import BuildVariant, ProjectConfig
from cmake_helpers import require_cmake


def test_cmake_release_fails_when_required_anvil_define_missing(
    tmp_path: Path,
    available_compiler: str,
    cmake_flags_asset_root: Path,
) -> None:
    require_cmake()
    assert cmake_flags_asset_root.exists()

    build_base = tmp_path / "build"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = ProjectConfig(
        name="cmake_negative_test",
        build_dir=str(build_base),
        cmake_target="anvil_cmake_flags",
        cmake_build_type="Release",
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_missing_define_variant",
        compiler=available_compiler,
        standard="c++20",
        cxx_flags=(),
        defines=(),
    )

    with pytest.raises(RuntimeError):
        build_cmake(
            root=cmake_flags_asset_root,
            config=config,
            out_dir=out_dir,
            variant=variant,
            build_type="Release",
        )
