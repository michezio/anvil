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
    assert return_code == 1
    assert built == expected_built
    assert [entry["name"] for entry in summary] == expected_built
    assert summary[-1 if stop_on_error else 1]["error"] == "expected failure"