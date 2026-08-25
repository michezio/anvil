import json
import shutil
from pathlib import Path

import pytest

from anvil.build import build_cmake
from anvil.models import BuildVariant, ProjectConfig
from conftest import resolve_artifact_path


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

    artifact = resolve_artifact_path(Path(metadata["artifact"]))
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

    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in cache_text
    assert "-DFROM_ANVIL_DEFINES=1" in cache_text
    assert "-DANVIL_EXPECT_RELEASE=1" in cache_text

    if "CMAKE_BUILD_TYPE:STRING=" in cache_text:
        assert "CMAKE_BUILD_TYPE:STRING=Release" in cache_text


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

    build_failed = False
    try:
        metadata = build_cmake(
            root=cmake_flags_asset_root,
            config=config,
            out_dir=out_dir,
            variant=variant,
            build_type="Release",
        )
    except RuntimeError:
        build_failed = True
        metadata = None

    build_dir = Path(config.build_dir) / variant.name / "release"
    cache_file = build_dir / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")

    # build.py now writes variant flags to CMAKE_CXX_FLAGS_<CONFIG> using fallback "Release".
    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in cache_text
    assert "-DFROM_ANVIL_DEFINES=1" in cache_text

    is_multi_config = "CMAKE_CONFIGURATION_TYPES:STRING=" in cache_text
    if is_multi_config:
        # Multi-config generators (e.g. Visual Studio) do not use CMAKE_BUILD_TYPE.
        assert "CMAKE_BUILD_TYPE:STRING=" not in cache_text
        assert build_failed is False
        assert metadata is not None
        artifact = resolve_artifact_path(Path(metadata["artifact"]))
        assert artifact.exists()
    else:
        # Single-config generators expose CMAKE_BUILD_TYPE, but we did not set it.
        assert "CMAKE_BUILD_TYPE:STRING=" in cache_text
        assert "CMAKE_BUILD_TYPE:STRING=Release" not in cache_text
        assert build_failed is True
