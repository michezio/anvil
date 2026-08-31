import json
import sys
from pathlib import Path

import pytest

import anvil.cli
from anvil.cli import _select_variants
from anvil.models import BuildVariant


@pytest.fixture
def variants() -> list[BuildVariant]:
    return [
        BuildVariant(name="gcc_O2"),
        BuildVariant(name="gcc_O3"),
        BuildVariant(name="clang_O2"),
    ]


def test_variant_selection_combines_exact_names_and_globs(
    variants: list[BuildVariant],
) -> None:
    selected = _select_variants(variants, ["clang_O2"], ["gcc_O?"])
    assert [variant.name for variant in selected] == ["gcc_O2", "gcc_O3", "clang_O2"]


def test_variant_selection_rejects_unknown_exact_name(variants: list[BuildVariant]) -> None:
    with pytest.raises(ValueError, match="Unknown variant name.*missing"):
        _select_variants(variants, ["missing"], [])


def test_variant_selection_rejects_empty_match(variants: list[BuildVariant]) -> None:
    with pytest.raises(ValueError, match="matched no variants"):
        _select_variants(variants, [], ["msvc_*"])


def test_variant_selection_defaults_to_all_variants(variants: list[BuildVariant]) -> None:
    assert _select_variants(variants, [], []) == variants


@pytest.mark.parametrize("option", ["--list-variants", "--dry-run"])
def test_planning_commands_do_not_build_or_create_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    option: str,
) -> None:
    source = tmp_path / "main.cpp"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    variants_file = tmp_path / "anvil_variants.json"
    variants_file.write_text(
        json.dumps({"variants": [{"name": "gcc_O2"}, {"name": "clang_O2"}]}),
        encoding="utf-8",
    )
    output = tmp_path / ".out"
    project_file = tmp_path / "anvil_project.json"
    project_file.write_text(
        json.dumps({"name": "test", "out_dir": str(output)}), encoding="utf-8"
    )

    def fail_if_called(*args: object, **kwargs: object) -> int:
        raise AssertionError("planning command invoked a builder")

    monkeypatch.setattr(anvil.cli, "_run_direct_matrix", fail_if_called)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "anvil",
            "--target",
            str(source),
            "--project",
            str(project_file),
            "--variants",
            str(variants_file),
            "--match",
            "gcc_*",
            option,
        ],
    )

    assert anvil.cli.main() == 0
    assert "gcc_O2" in capsys.readouterr().out
    assert not output.exists()