import json
from pathlib import Path

from anvil.build import build_direct
from anvil.models import BuildVariant, ProjectConfig
from conftest import resolve_artifact_path
import pytest


def test_direct_build_variant_flags_and_defines(tmp_path: Path, available_compiler: str) -> None:
    src = tmp_path / "main.cpp"
    src.write_text(
        """
#ifndef ANVIL_DIRECT_VARIANT
#error ANVIL_DIRECT_VARIANT must be defined
#endif

static_assert(ANVIL_DIRECT_VARIANT == 7, "define value mismatch");

int main() {
    return 0;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    variant = BuildVariant(
        name="direct_variant",
        compiler=available_compiler,
        standard="c++20",
        cxx_flags=("-O2", "-Wall"),
        defines=("ANVIL_DIRECT_VARIANT=7",),
    )
    config = ProjectConfig(name="direct_test")

    metadata = build_direct(
        sources=[src],
        include_dir=tmp_path,
        out_dir=out_dir,
        output_name="direct_app",
        variant=variant,
        config=config,
    )

    artifact = resolve_artifact_path(Path(metadata["artifact"]))
    assert artifact.exists()
    assert artifact.stat().st_size > 0

    metadata_file = out_dir / "direct_app__direct_variant.json"
    saved = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert saved["effective_flags"] == "-O2 -Wall -DANVIL_DIRECT_VARIANT=7"
    assert saved["cxx_flags"] == ["-O2", "-Wall"]
    assert saved["defines"] == ["ANVIL_DIRECT_VARIANT=7"]
    assert saved["compiler"] == available_compiler


def test_direct_build_fails_when_required_define_missing(tmp_path: Path, available_compiler: str) -> None:
    src = tmp_path / "main.cpp"
    src.write_text(
        """
#ifndef ANVIL_DIRECT_VARIANT
#error ANVIL_DIRECT_VARIANT must be defined
#endif

int main() {
    return 0;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    variant = BuildVariant(
        name="direct_variant_missing_define",
        compiler=available_compiler,
        standard="c++20",
        cxx_flags=("-O0",),
        defines=(),
    )
    config = ProjectConfig(name="direct_test_negative")

    with pytest.raises(RuntimeError):
        build_direct(
            sources=[src],
            include_dir=tmp_path,
            out_dir=out_dir,
            output_name="direct_app",
            variant=variant,
            config=config,
        )
