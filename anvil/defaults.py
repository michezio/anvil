DEFAULT_VARIANTS_DATA: dict[str, list[dict]] = {
    "bases": [
        {
            "name": "base_gcc",
            "compiler": "g++",
            "standard": "c++23",
            "cxx_flags": [],
            "defines": [],
        }
    ],
    "variants": [
        {
            "name": "gcc_O0",
            "base": "base_gcc",
            "cxx_flags": ["-O0"]
        },
        {
            "name": "gcc_O1",
            "base": "base_gcc",
            "cxx_flags": ["-O1"]
        },
        {
            "name": "gcc_O2",
            "base": "base_gcc",
            "cxx_flags": ["-O2"]
        },
        {
            "name": "gcc_O3",
            "base": "base_gcc",
            "cxx_flags": ["-O3"]
        },
        {
            "name": "gcc_Ofast",
            "base": "base_gcc",
            "cxx_flags": ["-Ofast", "-ffast-math"]
        },
    ],
}
