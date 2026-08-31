import json
from pathlib import Path

import pytest

from anvil.config import parse_variants


def test_variants_base_flags_and_defines_are_extended(tmp_path: Path) -> None:
    variants_json = tmp_path / "anvil_variants.json"
    variants_json.write_text(
        json.dumps(
            {
                "bases": [
                    {
                        "name": "base_gcc",
                        "compiler": "g++",
                        "c_compiler": "gcc",
                        "cxx_compiler": "g++",
                        "standard": "c++23",
                        "c_flags": ["-Wstrict-prototypes"],
                        "cxx_flags": ["-O2", "-fPIC"],
                        "defines": ["BASE=1"],
                        "c_defines": ["C_ONLY=1"],
                        "cxx_defines": ["CXX_ONLY=1"],
                    }
                ],
                "variants": [
                    {
                        "name": "debug_plus",
                        "base": "base_gcc",
                        "c_flags": ["-O1"],
                        "cxx_flags": ["-g"],
                        "defines": ["EXTRA=1"],
                        "c_defines": ["C_EXTRA=1"],
                        "cxx_defines": ["CXX_EXTRA=1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    variants = parse_variants(variants_json)
    assert len(variants) == 1

    variant = variants[0]
    assert variant.name == "debug_plus"
    assert variant.compiler == "g++"
    assert variant.c_compiler == "gcc"
    assert variant.cxx_compiler == "g++"
    assert variant.standard == "c++23"
    assert variant.c_flags == ("-Wstrict-prototypes", "-O1")
    assert variant.cxx_flags == ("-O2", "-fPIC", "-g")
    assert variant.defines == ("BASE=1", "EXTRA=1")
    assert variant.c_defines == ("C_ONLY=1", "C_EXTRA=1")
    assert variant.cxx_defines == ("CXX_ONLY=1", "CXX_EXTRA=1")


@pytest.mark.parametrize("name", ["../escape", "with space", "/absolute", "", ".hidden"])
def test_variant_names_must_be_safe_path_components(tmp_path: Path, name: str) -> None:
    variants_json = tmp_path / "anvil_variants.json"
    variants_json.write_text(json.dumps({"variants": [{"name": name}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="missing non-empty|Unsafe variant name"):
        parse_variants(variants_json)


def test_duplicate_variant_names_are_rejected(tmp_path: Path) -> None:
    variants_json = tmp_path / "anvil_variants.json"
    variants_json.write_text(
        json.dumps({"variants": [{"name": "same"}, {"name": "same"}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Duplicate variant name 'same'"):
        parse_variants(variants_json)
