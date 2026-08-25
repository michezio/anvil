import json
import shutil
import sys
from pathlib import Path

import pytest

from anvil.cli import main as anvil_main
from anvil.build import build_cmake
from anvil.models import BuildVariant, ProjectConfig
from conftest import normalize_flag_tokens, resolve_artifact_path


def _cache_value(cache_text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in cache_text.splitlines():
        if line.startswith(prefix):
            return line.partition("=")[2]
    return ""


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
        defines=("FROM_ANVIL_DEFINES=1", "ANVIL_EXPECT_RELEASE=1", "ANVIL_EXPECT_NDEBUG=1"),
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
        == "-DFROM_ANVIL_CXXFLAGS=1 -O3 -DFROM_ANVIL_DEFINES=1 -DANVIL_EXPECT_RELEASE=1 -DANVIL_EXPECT_NDEBUG=1"
    )
    assert saved["compiler"] == available_compiler

    cache_file = Path(saved["build_dir"]) / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")
    release_flags = _cache_value(cache_text, "CMAKE_CXX_FLAGS_RELEASE")
    release_tokens = normalize_flag_tokens(release_flags)

    assert "CMAKE_CXX_FLAGS_RELEASE:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in release_tokens
    assert "-DFROM_ANVIL_DEFINES=1" in release_tokens
    assert "-DANVIL_EXPECT_RELEASE=1" in release_tokens
    assert "-DANVIL_EXPECT_NDEBUG=1" in release_tokens
    # Standard release defaults should be preserved and Anvil flags appended.
    assert "-DNDEBUG" in release_tokens

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


def test_cmake_release_fails_when_required_anvil_define_missing(
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


def test_cmake_custom_config_uses_anvil_blank_state(
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
    custom_flags = _cache_value(cache_text, "CMAKE_CXX_FLAGS_ANVILCUSTOM")
    custom_tokens = normalize_flag_tokens(custom_flags)

    assert "CMAKE_CXX_FLAGS_ANVILCUSTOM:STRING=" in cache_text
    assert "-DFROM_ANVIL_CXXFLAGS=1" in custom_tokens
    assert "-DFROM_ANVIL_DEFINES=1" in custom_tokens
    # Custom config should be a blank state controlled by Anvil flags only.
    assert "-DFROM_CMAKELISTS_RELEASE=1" not in custom_tokens
    assert "-DNDEBUG" not in custom_tokens


def test_cmake_project_with_json_configuration_files(
    tmp_path: Path,
    available_compiler: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is required for this test")

    project_root = tmp_path / "json_cfg_project"
    project_root.mkdir(parents=True, exist_ok=True)

    (project_root / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(anvil_json_cfg_project LANGUAGES CXX)
add_executable(json_cfg_app main.cpp)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    (project_root / "main.cpp").write_text(
        """
#ifndef FROM_JSON_CXXFLAGS
#error FROM_JSON_CXXFLAGS must be provided by variant cxx_flags
#endif

#ifndef FROM_JSON_DEFINES
#error FROM_JSON_DEFINES must be provided by variant defines
#endif

int main() {
    return 0;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "json_cfg_out"
    build_dir = tmp_path / "json_cfg_build"

    project_cfg = project_root / "anvil_project.json"
    project_cfg.write_text(
        json.dumps(
            {
                "name": "json_cfg_project",
                "build_dir": str(build_dir),
                "out_dir": str(out_dir),
                "cmake": {
                    "target": "json_cfg_app",
                    "build_type": "Release",
                    "args": [],
                },
                "jobs": 1,
                "parallel_variants": 1,
                "stop_on_error": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    variants_cfg = project_root / "anvil_variants.json"
    variants_cfg.write_text(
        json.dumps(
            {
                "variants": [
                    {
                        "name": "json_cfg_variant",
                        "compiler": available_compiler,
                        "standard": "c++20",
                        "cxx_flags": ["-DFROM_JSON_CXXFLAGS=1"],
                        "defines": ["FROM_JSON_DEFINES=1"],
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "anvil",
            "--target",
            str(project_root),
            "--project",
            str(project_cfg),
            "--variants",
            str(variants_cfg),
        ],
    )

    exit_code = anvil_main()
    assert exit_code == 0

    metadata_file = out_dir / "json_cfg_app__json_cfg_variant.json"
    assert metadata_file.exists()
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["name"] == "json_cfg_variant"
    assert metadata["compiler"] == available_compiler
    assert "-DFROM_JSON_CXXFLAGS=1" in metadata["effective_flags"]
    assert "-DFROM_JSON_DEFINES=1" in metadata["effective_flags"]

    artifact = resolve_artifact_path(Path(metadata["artifact"]))
    assert artifact.exists()
    assert artifact.stat().st_size > 0

    summary_file = out_dir / "build_summary.json"
    assert summary_file.exists()
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert len(summary) == 1
    assert summary[0]["name"] == "json_cfg_variant"
    assert "error" not in summary[0]
