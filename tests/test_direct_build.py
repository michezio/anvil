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


def test_direct_mixed_language_build_uses_language_specific_payloads(
    tmp_path: Path, available_compiler: str, available_c_compiler: str
) -> None:
    cpp_source = tmp_path / "main.cpp"
    cpp_source.write_text(
        """
#ifndef CXX_ONLY
#error CXX_ONLY must be defined for C++
#endif
extern "C" int c_value(void);
int main() { return c_value() == 7 ? 0 : 1; }
""".strip()
        + "\n",
        encoding="utf-8",
    )
    c_source = tmp_path / "support.c"
    c_source.write_text(
        """
#ifdef CXX_ONLY
#error CXX_ONLY must not be defined for C
#endif
#ifndef C_ONLY
#error C_ONLY must be defined for C
#endif
#ifndef SHARED
#error SHARED must be defined for both languages
#endif
int c_value(void) { return 7; }
""".strip()
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    variant = BuildVariant(
        name="mixed",
        compiler=available_compiler,
        c_compiler=available_c_compiler,
        standard="c++20",
        c_flags=("-Wall",),
        cxx_flags=("-Wall",),
        defines=("SHARED=1",),
        c_defines=("C_ONLY=1",),
        cxx_defines=("CXX_ONLY=1",),
    )

    metadata = build_direct(
        sources=[cpp_source, c_source],
        include_dir=tmp_path,
        out_dir=out_dir,
        output_name="mixed_app",
        variant=variant,
        config=ProjectConfig(),
    )

    assert Path(metadata["artifact"]).exists()
    c_command = next(command for command in metadata["compile_commands"] if str(c_source) in command)
    cxx_command = next(command for command in metadata["compile_commands"] if str(cpp_source) in command)
    assert "-DC_ONLY=1" in c_command
    assert "-DCXX_ONLY=1" not in c_command
    assert "-DCXX_ONLY=1" in cxx_command
    assert "-DC_ONLY=1" not in cxx_command
