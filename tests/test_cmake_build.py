import json
import shutil
from pathlib import Path

import pytest

from anvil.build import build_cmake
from anvil.models import BuildVariant, ProjectConfig


def test_cmake_flags_from_env_and_cmakelists_interact_with_release(
    tmp_path: Path,
    available_compiler: str,
    cmake_flags_asset_root: Path,
) -> None:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is required for this test")
    assert cmake_flags_asset_root.exists()

    build_base = tmp_path / "build"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = ProjectConfig(
        name="cmake_flags_test",
        build_dir=str(build_base),
        cmake_target="anvil_cmake_flags",
        cmake_build_type="Release",
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_flags_variant",
        compiler=available_compiler,
        standard="c++20",
        cxx_flags=("-DFROM_ANVIL_CXXFLAGS=1", "-O3"),
        defines=("FROM_ANVIL_DEFINES=1", "ANVIL_EXPECT_RELEASE=1"),
    )

    metadata = build_cmake(
        root=cmake_flags_asset_root,
        config=config,
        out_dir=out_dir,
        variant=variant,
        build_type="Release",
    )

    artifact = Path(metadata["artifact"])
    assert artifact.exists()
    assert artifact.stat().st_size > 0

    metadata_file = out_dir / "anvil_cmake_flags__cmake_flags_variant.json"
    saved = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert (
        saved["effective_flags"]
        == "-DFROM_ANVIL_CXXFLAGS=1 -O3 -DFROM_ANVIL_DEFINES=1 -DANVIL_EXPECT_RELEASE=1"
    )
    assert saved["compiler"] == available_compiler

    cache_file = Path(saved["build_dir"]) / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")

    assert "CMAKE_CXX_FLAGS:STRING=" in cache_text
    assert "CMAKE_BUILD_TYPE:STRING=Release" in cache_text
    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in cache_text
    assert "-DFROM_ANVIL_DEFINES=1" in cache_text
    assert "-DANVIL_EXPECT_RELEASE=1" in cache_text

    flags_file = Path(saved["build_dir"]) / "CMakeFiles" / "anvil_cmake_flags.dir" / "flags.make"
    flags_text = flags_file.read_text(encoding="utf-8")
    assert "CXX_FLAGS =" in flags_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in flags_text
    assert "-DFROM_ANVIL_DEFINES=1" in flags_text
    assert "-DFROM_CMAKELISTS_GLOBAL=1" in flags_text
    assert "-DFROM_CMAKELISTS_RELEASE=1" in flags_text
    # New behavior: explicit CMAKE_CXX_FLAGS_RELEASE from anvil may replace compiler default release flags.
    assert "-DNDEBUG" not in flags_text


def test_cmake_flags_without_explicit_build_type(
    tmp_path: Path,
    available_compiler: str,
    cmake_flags_asset_root: Path,
) -> None:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is required for this test")
    assert cmake_flags_asset_root.exists()

    build_base = tmp_path / "build"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = ProjectConfig(
        name="cmake_no_build_type_test",
        build_dir=str(build_base),
        cmake_target="anvil_cmake_flags",
        cmake_build_type="",
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_no_build_type_variant",
        compiler=available_compiler,
        standard="c++20",
        cxx_flags=("-DFROM_ANVIL_CXXFLAGS=1",),
        defines=("FROM_ANVIL_DEFINES=1",),
    )

    with pytest.raises(RuntimeError):
        build_cmake(
            root=cmake_flags_asset_root,
            config=config,
            out_dir=out_dir,
            variant=variant,
            build_type="Release",
        )

    build_dir = Path(config.build_dir) / variant.name / "release"
    cache_file = build_dir / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")

    # build.py now writes variant flags to CMAKE_CXX_FLAGS_<CONFIG> using fallback "Release".
    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in cache_text
    assert "-DFROM_ANVIL_DEFINES=1" in cache_text

    # But without CMAKE_BUILD_TYPE set, single-config generators won't consume release-specific flags.
    assert "CMAKE_BUILD_TYPE:STRING=" in cache_text
    assert "CMAKE_BUILD_TYPE:STRING=Release" not in cache_text

    flags_file = build_dir / "CMakeFiles" / "anvil_cmake_flags.dir" / "flags.make"
    flags_text = flags_file.read_text(encoding="utf-8")
    assert "-DFROM_ANVIL_CXXFLAGS=1" not in flags_text
    assert "-DFROM_ANVIL_DEFINES=1" not in flags_text
    assert "-DFROM_CMAKELISTS_GLOBAL=1" in flags_text
    assert "-DFROM_CMAKELISTS_RELEASE=1" not in flags_text
