import json
from pathlib import Path

from anvil.build import build_cmake
from anvil.models import BuildVariant, ProjectConfig
from cmake_helpers import cache_value, require_cmake
from conftest import normalize_flag_tokens, resolve_artifact_path


def test_cmake_flags_from_env_and_cmakelists_interact_with_release(
    tmp_path: Path,
    available_compiler: str,
    cmake_flags_asset_root: Path,
) -> None:
    require_cmake()
    assert cmake_flags_asset_root.exists()

    build_base = tmp_path / "build"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    toolchain_file = tmp_path / "toolchain.cmake"
    toolchain_file.write_text(
        'set(ANVIL_TOOLCHAIN_MARKER "loaded" CACHE STRING "")\n', encoding="utf-8"
    )

    config = ProjectConfig(
        name="cmake_flags_test",
        build_dir=str(build_base),
        cmake_target="anvil_cmake_flags",
        cmake_build_type="Release",
        cmake_toolchain_file=str(toolchain_file),
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_flags_variant",
        compiler=available_compiler,
        standard="c++20",
        c_flags=("-DFROM_ANVIL_CFLAGS=1",),
        cxx_flags=("-DFROM_ANVIL_CXXFLAGS=1", "-O3"),
        defines=("FROM_ANVIL_DEFINES=1", "ANVIL_EXPECT_RELEASE=1", "ANVIL_EXPECT_NDEBUG=1"),
        c_defines=("FROM_ANVIL_C_DEFINES=1",),
        cxx_defines=("FROM_ANVIL_CXX_DEFINES=1",),
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
        == "-DFROM_ANVIL_CXXFLAGS=1 -O3 -DFROM_ANVIL_DEFINES=1 -DANVIL_EXPECT_RELEASE=1 -DANVIL_EXPECT_NDEBUG=1 -DFROM_ANVIL_CXX_DEFINES=1"
    )
    assert saved["compiler"] == available_compiler

    cache_file = Path(saved["build_dir"]) / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")
    release_flags = cache_value(cache_text, "CMAKE_CXX_FLAGS_RELEASE")
    release_tokens = normalize_flag_tokens(release_flags)
    c_release_flags = cache_value(cache_text, "CMAKE_C_FLAGS_RELEASE")
    c_release_tokens = normalize_flag_tokens(c_release_flags)

    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in release_tokens
    assert "-DFROM_ANVIL_DEFINES=1" in release_tokens
    assert "-DANVIL_EXPECT_RELEASE=1" in release_tokens
    assert "-DANVIL_EXPECT_NDEBUG=1" in release_tokens
    assert "-DFROM_ANVIL_CXX_DEFINES=1" in release_tokens
    assert "-DFROM_ANVIL_CFLAGS=1" not in release_tokens
    assert "-DNDEBUG" in release_tokens
    assert "-DFROM_ANVIL_CFLAGS=1" in c_release_tokens
    assert "-DFROM_ANVIL_C_DEFINES=1" in c_release_tokens
    assert "-DFROM_ANVIL_DEFINES=1" in c_release_tokens
    assert "-DFROM_ANVIL_CXXFLAGS=1" not in c_release_tokens
    assert cache_value(cache_text, "CMAKE_CXX_STANDARD") == "20"
    assert cache_value(cache_text, "CMAKE_CXX_STANDARD_REQUIRED") == "ON"
    assert cache_value(cache_text, "CMAKE_CXX_EXTENSIONS") == "OFF"
    assert cache_value(cache_text, "ANVIL_TOOLCHAIN_MARKER") == "loaded"
    assert saved["resolved_cxx_compiler"]
    assert saved["compiler_version"]
    assert saved["cmake_version"].startswith("cmake version")
    assert len(saved["artifact_sha256"]) == 64
    assert saved["toolchain_file"] == str(toolchain_file)
    assert len(saved["toolchain_sha256"]) == 64
    assert Path(saved["compile_commands"]).exists()

    if "CMAKE_BUILD_TYPE:STRING=" in cache_text:
        assert "CMAKE_BUILD_TYPE:STRING=Release" in cache_text


def test_cmake_flags_without_explicit_build_type(
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

    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in cache_text
    assert "-DFROM_ANVIL_DEFINES=1" in cache_text

    is_multi_config = "CMAKE_CONFIGURATION_TYPES:STRING=" in cache_text
    if is_multi_config:
        assert "CMAKE_BUILD_TYPE:STRING=" not in cache_text
        assert build_failed is False
        assert metadata is not None
        artifact = resolve_artifact_path(Path(metadata["artifact"]))
        assert artifact.exists()
    else:
        # build.py now sets selected target config as CMAKE_BUILD_TYPE.
        assert "CMAKE_BUILD_TYPE:STRING=Release" in cache_text
        assert build_failed is False
        assert metadata is not None


def test_cmake_custom_config_uses_anvil_blank_state(
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
        name="cmake_custom_config_test",
        build_dir=str(build_base),
        cmake_target="anvil_cmake_flags",
        cmake_build_type="AnvilCustom",
        cmake_args=("-DCMAKE_CONFIGURATION_TYPES=Debug;Release;AnvilCustom",),
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_custom_variant",
        compiler=available_compiler,
        standard="c++20",
        cxx_flags=("-DFROM_ANVIL_CXXFLAGS=1",),
        defines=("FROM_ANVIL_DEFINES=1",),
    )

    metadata = build_cmake(
        root=cmake_flags_asset_root,
        config=config,
        out_dir=out_dir,
        variant=variant,
        build_type="AnvilCustom",
    )

    artifact = resolve_artifact_path(Path(metadata["artifact"]))
    assert artifact.exists()
    assert artifact.stat().st_size > 0

    cache_file = Path(metadata["build_dir"]) / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")
    custom_flags = cache_value(cache_text, "CMAKE_CXX_FLAGS_ANVILCUSTOM")
    custom_tokens = normalize_flag_tokens(custom_flags)

    assert "CMAKE_CXX_FLAGS_ANVILCUSTOM:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in custom_tokens
    assert "-DFROM_ANVIL_DEFINES=1" in custom_tokens
    assert "-DFROM_CMAKELISTS_RELEASE=1" not in custom_tokens
    assert "-DNDEBUG" not in custom_tokens
