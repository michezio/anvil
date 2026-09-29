import json
import os
from pathlib import Path

import pytest

import anvil.build
from anvil.build import build_cmake
from anvil.models import BuildVariant, ProjectConfig
from cmake_helpers import cache_value, require_cmake
from conftest import normalize_flag_tokens


@pytest.fixture
def mixed_language_cmake_args() -> tuple[str, ...]:
    return ("-G", "Ninja") if os.name == "nt" else ()


def test_cmake_flags_from_env_and_cmakelists_interact_with_release(
    tmp_path: Path,
    available_compiler: str,
    available_c_compiler: str,
    cmake_flags_asset_root: Path,
    mixed_language_cmake_args: tuple[str, ...],
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
        cmake_args=mixed_language_cmake_args,
        cmake_toolchain_file=str(toolchain_file),
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_flags_variant",
        compiler=available_compiler,
        c_compiler=available_c_compiler,
        cxx_compiler=available_compiler,
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

    artifact = Path(metadata["artifact"])
    assert artifact.is_file()
    assert artifact.stat().st_size > 0

    metadata_file = out_dir / "anvil_cmake_flags__cmake_flags_variant.json"
    saved = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert (
        saved["effective_flags"]
        == "-DFROM_ANVIL_CXXFLAGS=1 -O3 -DFROM_ANVIL_DEFINES=1 -DANVIL_EXPECT_RELEASE=1 -DANVIL_EXPECT_NDEBUG=1 -DFROM_ANVIL_CXX_DEFINES=1"
    )
    assert saved["compiler"] == available_compiler
    assert saved["artifact"] == str(artifact)

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
    available_c_compiler: str,
    cmake_flags_asset_root: Path,
    mixed_language_cmake_args: tuple[str, ...],
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
        cmake_args=mixed_language_cmake_args,
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_no_build_type_variant",
        compiler=available_compiler,
        c_compiler=available_c_compiler,
        cxx_compiler=available_compiler,
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
        assert Path(metadata["artifact"]).is_file()
    else:
        # build.py now sets selected target config as CMAKE_BUILD_TYPE.
        assert "CMAKE_BUILD_TYPE:STRING=Release" in cache_text
        assert build_failed is False
        assert metadata is not None


def test_cmake_custom_config_uses_anvil_blank_state(
    tmp_path: Path,
    available_compiler: str,
    available_c_compiler: str,
    cmake_flags_asset_root: Path,
    mixed_language_cmake_args: tuple[str, ...],
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
        cmake_args=(*mixed_language_cmake_args, "-DCMAKE_CONFIGURATION_TYPES=Debug;Release;AnvilCustom"),
        jobs=1,
    )
    variant = BuildVariant(
        name="cmake_custom_variant",
        compiler=available_compiler,
        c_compiler=available_c_compiler,
        cxx_compiler=available_compiler,
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

    artifact = Path(metadata["artifact"])
    assert artifact.is_file()
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


@pytest.mark.parametrize("build_type", ["Release", "Anvil-Custom"])
@pytest.mark.parametrize("languages", [("CXX",), ("C", "CXX")])
def test_multi_config_cmake_keeps_languages_and_executable_path_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    build_type: str,
    languages: tuple[str, ...],
) -> None:
    build_dir = tmp_path / "build" / "variant" / build_type.lower()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    configure_commands: list[list[str]] = []
    build_commands: list[list[str]] = []

    def fake_run(command: list[str], *, verbose: bool = False) -> None:
        if "-S" in command:
            configure_commands.append(command)
            (build_dir / "CMakeCache.txt").write_text(
                "CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n"
                "CMAKE_C_FLAGS_RELEASE:STRING=/O2\n"
                "CMAKE_CXX_FLAGS_RELEASE:STRING=/O2 /DNDEBUG\n"
                "CMAKE_CXX_COMPILER:FILEPATH=C:/tools/cl.exe\n",
                encoding="utf-8",
            )
            reply_dir = build_dir / ".cmake" / "api" / "v1" / "reply"
            reply_dir.mkdir(parents=True, exist_ok=True)
            (reply_dir / "index-1.json").write_text(
                json.dumps({"reply": {"codemodel-v2": {"jsonFile": "codemodel.json"}}}),
                encoding="utf-8",
            )
            (reply_dir / "codemodel.json").write_text(
                json.dumps(
                    {"configurations": [{
                        "name": build_type,
                        "targets": [{"name": "app", "jsonFile": "target.json"}],
                    }]}
                ),
                encoding="utf-8",
            )
            (reply_dir / "target.json").write_text(
                json.dumps({"compileGroups": [{"language": name} for name in languages]}),
                encoding="utf-8",
            )
        else:
            build_commands.append(command)
            artifact = build_dir / build_type / "app.exe"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"executable")

    monkeypatch.setattr(anvil.build, "run_cmd", fake_run)
    monkeypatch.setattr(anvil.build, "_command_version", lambda command: "test version")
    config = ProjectConfig(
        name="windows",
        build_dir=str(tmp_path / "build"),
        cmake_target="app",
        cmake_build_type=build_type,
        jobs=1,
    )
    variant = BuildVariant(
        name="variant",
        c_flags=("-DC_ONLY=1",),
        cxx_flags=("-DCXX_ONLY=1",),
        defines=("SHARED=1",),
        c_defines=("C_DEFINE=1",),
        cxx_defines=("CXX_DEFINE=1",),
    )

    if len(languages) == 2:
        with pytest.raises(RuntimeError, match=r"Visual Studio cannot isolate C and C\+\+ flags"):
            build_cmake(tmp_path, config, out_dir, variant, build_type)
    else:
        metadata = build_cmake(tmp_path, config, out_dir, variant, build_type)

    cxx_key = "CMAKE_CXX_FLAGS_" + ("RELEASE" if build_type == "Release" else "ANVILCUSTOM")
    c_key = "CMAKE_C_FLAGS_" + ("RELEASE" if build_type == "Release" else "ANVILCUSTOM")
    assert not any(arg.startswith("-DCMAKE_BUILD_TYPE=") for cmd in configure_commands for arg in cmd)
    assert len(configure_commands) == (2 if build_type == "Release" else 1)
    c_flags = next(arg for arg in configure_commands[-1] if arg.startswith(f"-D{c_key}:STRING="))
    cxx_flags = next(arg for arg in configure_commands[-1] if arg.startswith(f"-D{cxx_key}:STRING="))
    assert "-DC_ONLY=1" in c_flags and "-DCXX_ONLY=1" not in c_flags
    assert "-DC_DEFINE=1" in c_flags and "-DCXX_DEFINE=1" not in c_flags
    assert "-DCXX_ONLY=1" in cxx_flags and "-DC_ONLY=1" not in cxx_flags
    assert "-DCXX_DEFINE=1" in cxx_flags and "-DC_DEFINE=1" not in cxx_flags
    assert "-DSHARED=1" in c_flags and "-DSHARED=1" in cxx_flags
    if len(languages) == 2:
        assert not build_commands
    else:
        assert build_commands[0][-2:] == ["--config", build_type]
        assert metadata["artifact"] == str(out_dir / "app__variant.exe")
        assert Path(metadata["artifact"]).is_file()
        assert len(metadata["artifact_sha256"]) == 64
