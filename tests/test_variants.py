import json
from pathlib import Path

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
                        "standard": "c++23",
                        "cxx_flags": ["-O2", "-fPIC"],
                        "defines": ["BASE=1"],
                    }
                ],
                "variants": [
                    {
                        "name": "debug_plus",
                        "base": "base_gcc",
                        "cxx_flags": ["-g"],
                        "defines": ["EXTRA=1"],
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
    assert variant.standard == "c++23"
    assert variant.cxx_flags == ("-O2", "-fPIC", "-g")
    assert variant.defines == ("BASE=1", "EXTRA=1")
