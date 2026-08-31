import json
import sys
from pathlib import Path

import pytest

import anvil.cli
from anvil.cli import main as anvil_main
from cmake_helpers import cache_value, require_cmake
from conftest import normalize_flag_tokens, resolve_artifact_path


def test_project_directory_is_the_default_target_and_boolean_can_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\n")
    (project_root / "anvil_project.json").write_text(
        json.dumps({"name": "project", "cmake": {"target": "app"}, "clean": True}),
        encoding="utf-8",
    )
    (project_root / "anvil_variants.json").write_text(
        json.dumps({"variants": [{"name": "default"}]}), encoding="utf-8"
    )
    captured: dict[str, object] = {}

    def fake_run(root: Path, config: object, *args: object, **kwargs: object) -> int:
        captured["root"] = root
        captured["config"] = config
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(anvil.cli, "_run_cmake_matrix", fake_run)
    monkeypatch.setattr(sys, "argv", ["anvil", "--project", str(project_root), "--no-clean"])

    assert anvil_main() == 0
    assert captured["root"] == project_root
    assert captured["config"].clean is False


def test_explicit_target_takes_precedence_over_project_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_root = tmp_path / "config"
    source_root = tmp_path / "source"
    config_root.mkdir()
    source_root.mkdir()
    (source_root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\n")
    project_config = config_root / "anvil_project.json"
    project_config.write_text(
        json.dumps({"name": "project", "cmake": {"target": "app"}}), encoding="utf-8"
    )
    variants_config = config_root / "anvil_variants.json"
    variants_config.write_text(
        json.dumps({"variants": [{"name": "default"}]}), encoding="utf-8"
    )
    captured: dict[str, Path] = {}

    def fake_run(root: Path, *args: object, **kwargs: object) -> int:
        captured["root"] = root
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(anvil.cli, "_run_cmake_matrix", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "anvil",
            "--project",
            str(project_config),
            "--variants",
            str(variants_config),
            "--target",
            str(source_root),
        ],
    )

    assert anvil_main() == 0
    assert captured["root"] == source_root


def test_cmake_project_with_json_configuration_files(
    tmp_path: Path,
    available_compiler: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_cmake()

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


def test_cmake_single_build_type_drives_config_and_target(
    tmp_path: Path,
    available_compiler: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_cmake()

    project_root = tmp_path / "split_cfg_project"
    project_root.mkdir(parents=True, exist_ok=True)

    (project_root / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(anvil_split_cfg_project LANGUAGES CXX)
add_executable(split_cfg_app main.cpp)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    (project_root / "main.cpp").write_text(
        """
int main() {
    return 0;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "split_cfg_out"
    build_dir = tmp_path / "split_cfg_build"

    project_cfg = project_root / "anvil_project.json"
    project_cfg.write_text(
        json.dumps(
            {
                "name": "split_cfg_project",
                "build_dir": str(build_dir),
                "out_dir": str(out_dir),
                "cmake": {
                    "target": "split_cfg_app",
                    "build_type": "AnvilCustom",
                    "args": ["-DCMAKE_CONFIGURATION_TYPES=Debug;Release;AnvilCustom"],
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
                        "name": "split_cfg_variant",
                        "compiler": available_compiler,
                        "standard": "c++20",
                        "cxx_flags": ["-DANVIL_CUSTOM_ONLY=1"],
                        "defines": [],
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

    metadata_file = out_dir / "split_cfg_app__split_cfg_variant.json"
    assert metadata_file.exists()
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["cmake_build_type"] == "AnvilCustom"

    cache_file = Path(metadata["build_dir"]) / "CMakeCache.txt"
    cache_text = cache_file.read_text(encoding="utf-8")
    custom_flags = cache_value(cache_text, "CMAKE_CXX_FLAGS_ANVILCUSTOM")
    custom_tokens = normalize_flag_tokens(custom_flags)
    assert "-DANVIL_CUSTOM_ONLY=1" in custom_tokens

    if "CMAKE_BUILD_TYPE:STRING=" in cache_text:
        assert "CMAKE_BUILD_TYPE:STRING=AnvilCustom" in cache_text