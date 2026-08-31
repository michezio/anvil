import json
from pathlib import Path

import pytest

from anvil.models import BuildVariant, ProjectConfig
from anvil.orchestrator import _run_cmake_matrix, _run_direct_matrix


@pytest.mark.parametrize("runner", ["direct", "cmake"])
@pytest.mark.parametrize(
    ("stop_on_error", "expected_built"),
    [(False, ["passing_first", "failing", "passing_last"]), (True, ["passing_first", "failing"])],
)
def test_matrix_failure_status_is_independent_of_continuation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: str,
    stop_on_error: bool,
    expected_built: list[str],
) -> None:
    variants = [
        BuildVariant(name="passing_first"),
        BuildVariant(name="failing"),
        BuildVariant(name="passing_last"),
    ]
    built: list[str] = []

    def fake_build(*args: object, **kwargs: object) -> dict:
        variant = kwargs.get("variant")
        if variant is None:
            variant = args[4]
        assert isinstance(variant, BuildVariant)
        built.append(variant.name)
        if variant.name == "failing":
            raise RuntimeError("expected failure")
        return {"name": variant.name, "artifact": str(tmp_path / variant.name)}

    config = ProjectConfig(cmake_target="app", stop_on_error=stop_on_error)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    if runner == "direct":
        monkeypatch.setattr("anvil.orchestrator.build_direct", fake_build)
        return_code = _run_direct_matrix(
            sources=[tmp_path / "main.cpp"],
            include_dir=tmp_path,
            out_dir=out_dir,
            output_name="app",
            variants=variants,
            config=config,
            extra_args=[],
        )
    else:
        monkeypatch.setattr("anvil.orchestrator.build_cmake", fake_build)
        return_code = _run_cmake_matrix(
            root=tmp_path,
            config=config,
            out_dir=out_dir,
            variants=variants,
            build_type="Release",
        )

    summary = json.loads((out_dir / "build_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert return_code == 1
    assert built == expected_built
    assert [entry["name"] for entry in summary] == expected_built
    assert summary[-1 if stop_on_error else 1]["error"] == "expected failure"
    assert manifest["complete"] is True
    assert [entry["status"] for entry in manifest["artifacts"]].count("failed") == 1


def test_matrix_removes_stale_target_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "app__stale").write_text("old", encoding="utf-8")
    (out_dir / "app__stale.json").write_text("{}", encoding="utf-8")
    unrelated = out_dir / "other__stale"
    unrelated.write_text("keep", encoding="utf-8")

    def fake_build(*args: object, **kwargs: object) -> dict:
        artifact = out_dir / "app__current"
        artifact.write_text("current", encoding="utf-8")
        return {"name": "current", "artifact": str(artifact)}

    monkeypatch.setattr("anvil.orchestrator.build_direct", fake_build)
    return_code = _run_direct_matrix(
        sources=[tmp_path / "main.cpp"],
        include_dir=tmp_path,
        out_dir=out_dir,
        output_name="app",
        variants=[BuildVariant(name="current")],
        config=ProjectConfig(),
        extra_args=[],
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert return_code == 0
    assert not (out_dir / "app__stale").exists()
    assert not (out_dir / "app__stale.json").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert manifest["complete"] is True
    assert manifest["artifacts"][0]["path"] == "app__current"
    assert len(manifest["artifacts"][0]["sha256"]) == 64


def test_interrupted_matrix_persists_partial_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = 0

    def fake_build(*args: object, **kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        artifact = out_dir / "app__first"
        artifact.write_text("first", encoding="utf-8")
        return {"name": "first", "artifact": str(artifact)}

    monkeypatch.setattr("anvil.orchestrator.build_direct", fake_build)
    return_code = _run_direct_matrix(
        sources=[tmp_path / "main.cpp"],
        include_dir=tmp_path,
        out_dir=out_dir,
        output_name="app",
        variants=[BuildVariant(name="first"), BuildVariant(name="second")],
        config=ProjectConfig(),
        extra_args=[],
    )

    summary = json.loads((out_dir / "build_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert return_code == 130
    assert [entry["name"] for entry in summary] == ["first"]
    assert manifest["complete"] is False
    assert manifest["interrupted"] is True