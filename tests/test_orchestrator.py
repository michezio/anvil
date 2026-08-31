import hashlib
import json
from concurrent.futures import Future
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


def test_resume_reuses_only_matching_untampered_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "main.cpp"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    build_calls = 0

    def fake_build(*args: object, **kwargs: object) -> dict:
        nonlocal build_calls
        build_calls += 1
        variant = kwargs["variant"]
        fingerprint = kwargs["fingerprint"]
        assert isinstance(variant, BuildVariant)
        assert isinstance(fingerprint, str)
        artifact = out_dir / f"app__{variant.name}"
        artifact.write_text("artifact", encoding="utf-8")
        metadata = {
            "name": variant.name,
            "artifact": str(artifact),
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "fingerprint": fingerprint,
        }
        (out_dir / f"app__{variant.name}.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return metadata

    monkeypatch.setattr("anvil.orchestrator.build_direct", fake_build)
    arguments = {
        "sources": [source],
        "include_dir": tmp_path,
        "out_dir": out_dir,
        "output_name": "app",
        "variants": [BuildVariant(name="cached")],
        "extra_args": [],
    }

    assert _run_direct_matrix(config=ProjectConfig(), **arguments) == 0
    assert _run_direct_matrix(config=ProjectConfig(resume=True), **arguments) == 0
    assert build_calls == 1

    (out_dir / "app__cached").write_text("tampered", encoding="utf-8")
    assert _run_direct_matrix(config=ProjectConfig(resume=True), **arguments) == 0
    assert build_calls == 2

    source.write_text("int main() { return 1; }\n", encoding="utf-8")
    assert _run_direct_matrix(config=ProjectConfig(resume=True), **arguments) == 0
    assert build_calls == 3


def test_cmake_parallel_variants_share_the_job_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted_jobs: list[int] = []

    class ImmediateExecutor:
        def __init__(self, max_workers: int) -> None:
            assert max_workers == 2

        def __enter__(self) -> "ImmediateExecutor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def submit(self, function: object, *args: object) -> Future:
            future: Future = Future()
            config = args[1]
            variant = args[3]
            submitted_jobs.append(config.jobs)
            future.set_result(
                {"name": variant.name, "artifact": str(tmp_path / variant.name)}
            )
            return future

        def shutdown(self, wait: bool, cancel_futures: bool) -> None:
            return None

    monkeypatch.setattr("anvil.orchestrator.ProcessPoolExecutor", ImmediateExecutor)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ProjectConfig(
        build_dir=str(tmp_path / "build"),
        cmake_target="app",
        jobs=8,
        parallel_variants=2,
    )

    return_code = _run_cmake_matrix(
        root=tmp_path,
        config=config,
        out_dir=out_dir,
        variants=[BuildVariant(name="one"), BuildVariant(name="two")],
        build_type="Release",
    )

    assert return_code == 0
    assert submitted_jobs == [4, 4]


def test_allowed_failure_does_not_fail_or_stop_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = []

    def fake_build(*args: object, **kwargs: object) -> dict:
        variant = kwargs["variant"]
        built.append(variant.name)
        if variant.name == "experimental":
            raise RuntimeError("unsupported flag")
        return {"name": variant.name, "artifact": str(tmp_path / variant.name)}

    monkeypatch.setattr("anvil.orchestrator.build_direct", fake_build)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return_code = _run_direct_matrix(
        sources=[],
        include_dir=tmp_path,
        out_dir=out_dir,
        output_name="app",
        variants=[
            BuildVariant(name="experimental", allow_failure=True),
            BuildVariant(name="supported"),
        ],
        config=ProjectConfig(stop_on_error=True),
        extra_args=[],
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert return_code == 0
    assert built == ["experimental", "supported"]
    assert manifest["artifacts"][0]["status"] == "allowed_failure"