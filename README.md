# Anvil

**Anvil** is a build-matrix tool for C/C++ projects. It compiles your code multiple times with different compilers, optimization levels, and compiler flags — all driven by simple JSON configuration files.

Perfect for:
- **Benchmarking** across compiler configurations (GCC, Clang, Zig, etc.)
- **Testing** code with different optimization levels and build flags
- **CI/CD** workflows that need multi-variant builds
- **Exploring** compiler behavior with systematically varied flags

## Features

- **Three build modes**: Direct file compilation, folder recursion, or CMake projects
- **Multi-compiler support**: GCC, Clang, Zig, etc. (any compiler with a compatible CLI)
- **Per-variant configuration**: Each variant specifies compiler, C++ standard, optimization flags, and defines
- **Parallel builds**: Build multiple variants simultaneously for faster turnaround
- **Config discovery**: Looks for project config files named `anvil_project.json` or `anvil.project.json`, and variant files named `anvil_variants.json` or `anvil.variants.json` near the target or project directory
- **Flexible output**: Artifacts and metadata collected in a single directory
- **Cross-platform CMake execution**: Works with single-config and multi-config generators (Linux/macOS/Windows)

## Installation

### From source (editable)

```bash
git clone https://github.com/michezio/anvil.git
cd anvil
pip install -e .
```

Then use as:
```bash
python -m anvil --target myfile.cpp
# or
anvil --target myfile.cpp
```

### From PyPI (future)

```bash
pip install anvil-matrix
anvil --target myfile.cpp
```

## Quick Start

### 1. Compile a single file with default variants

```bash
python -m anvil --target src/myapp.cpp
```

Produces five binaries (O0, O1, O2, O3, Ofast):
```
.out/anvil_build/myapp/
  ├── myapp__gcc_O0
  ├── myapp__gcc_O1
  ├── myapp__gcc_O2
  ├── myapp__gcc_O3
  ├── myapp__gcc_Ofast
  └── build_summary.json
```

### 2. Compile all files in a folder

```bash
python -m anvil --target src/myproject/
```

### 3. Use custom variants

Create a variants file such as `anvil_variants_quick.json` (the repository examples use the same underscore-based naming):

```json
{
  "bases": [
    {
      "name": "base_gcc",
      "compiler": "g++",
      "standard": "c++23",
      "cxx_flags": [],
      "defines": []
    }
  ],
  "variants": [
    {
      "name": "gcc_O3",
      "base": "base_gcc",
      "cxx_flags": ["-O3"]
    },
    {
      "name": "gcc_Ofast",
      "base": "base_gcc",
      "cxx_flags": ["-Ofast", "-ffast-math"]
    }
  ]
}
```

Then point Anvil at it explicitly:

```bash
python -m anvil --target src/myapp.cpp --variants path/to/anvil_variants_quick.json
```

### 4. Control build behavior with config files

Create `anvil_project.json` next to your source. The sample project config in this repository uses the same nested `cmake` shape:

```json
{
  "name": "myproject",
  "build_dir": "/build/anvil/myproject",
  "out_dir": ".out/anvil_build/myproject",
  "cmake": {
    "target": "my_target",
    "build_type": "Release",
    "args": []
  },
  "include_dirs": ["/opt/deps/include"],
  "link_flags": "-L/opt/deps/lib -lmydep",
  "jobs": 0,
  "parallel_variants": 4,
  "stop_on_error": false,
  "clean": false,
  "verbose": false
}
```

Then:
```bash
python -m anvil --target src/ --project path/to/anvil_project.json
```

## Configuration

### `anvil_project.json`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (inferred from parent directory) | Project name, used in output paths |
| `build_dir` | string | `/build/anvil/<name>` | CMake build directory (CMake mode) |
| `out_dir` | string | `.out/anvil_build/<name>` | Output directory for artifacts |
| `cmake.target` | string | `""` | CMake target name (required for CMake mode) |
| `cmake.build_type` | string | `""` | Explicit CMake build type. If unset, Anvil still uses a fallback config name (`Release`) for config-specific flag injection and `--config` build selection. |
| `cmake.args` | array | `[]` | Extra `cmake` configure arguments |
| `env_setup` | string | `""` | Script to source before building |
| `include_dirs` | array | `[]` | Extra `-I` paths (direct mode) |
| `link_flags` | string | `""` | Extra linker flags |
| `jobs` | int | `0` | Compile jobs per variant (`0` = auto via Python CPU count) |
| `parallel_variants` | int | `1` | Number of variants to build simultaneously |
| `stop_on_error` | bool | `false` | Abort on first variant failure |
| `clean` | bool | `false` | Clean build directories before building |
| `verbose` | bool | `false` | Print full compiler commands |

### CMake Flag Behavior (Config-Aware)

In CMake mode, Anvil computes `effective_flags` from each variant (`cxx_flags` + `defines`) and applies them to `CMAKE_CXX_FLAGS_<CONFIG>` and `CMAKE_C_FLAGS_<CONFIG>`.

- **Standard configs** (`Debug`, `Release`, `RelWithDebInfo`, `MinSizeRel`):
  Anvil **appends** injected flags to existing CMake/toolchain defaults.
  This preserves defaults like release-style optimization and `NDEBUG`.

- **Custom configs** (for example `AnvilCustom`):
  Anvil treats these as a **blank state** and sets config-specific flags from the variant payload, without inheriting standard-config defaults.

This lets you keep normal CMake behavior for standard profiles, while using custom profiles for controlled experiments.

### Variants JSON

Anvil reads a top-level JSON object with a required `variants` array and an optional `bases` array. The file can be named `anvil_variants.json` or `anvil.variants.json`, or passed explicitly via `--variants`.

```json
{
  "bases": [
    {
      "name": "base_gcc",
      "compiler": "g++",
      "standard": "c++23",
      "cxx_flags": ["-Wall"],
      "defines": ["BASE=1"]
    }
  ],
  "variants": [
    {
      "name": "gcc_O3",
      "base": "base_gcc",
      "cxx_flags": ["-O3"],
      "defines": ["OPT=3"]
    },
    {
      "name": "clang_O2",
      "compiler": "clang++",
      "standard": "c++20",
      "cxx_flags": ["-O2"],
      "defines": []
    }
  ]
}
```

`base` behavior: if a variant sets `base`, then `cxx_flags` and `defines` are appended to the base values, and `compiler`/`standard` inherit from the base unless overridden.

Base fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Base identifier |
| `compiler` | string | `g++` | Compiler command (supports multi-word forms like `zig c++`) |
| `standard` | string | `c++23` | C++ standard flag (for example `c++20` or `c++23`) |
| `cxx_flags` | array | `[]` | Base compiler flags |
| `defines` | array | `[]` | Base preprocessor defines |

Variant fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Variant identifier |
| `base` | string | unset | Optional base name to inherit from |
| `compiler` | string | inherited / `g++` | Compiler command |
| `standard` | string | inherited / `c++23` | C++ standard flag |
| `cxx_flags` | array | `[]` | Variant flags appended to base flags |
| `defines` | array | `[]` | Variant defines appended to base defines |

## Command Line

```
usage: anvil [-h] [--target TARGET] [--project PROJECT] [--variants VARIANTS]
             [--clean] [--stop-on-error] [--jobs JOBS] [--parallel PARALLEL]
             [--verbose] [--extra-args [EXTRA_ARGS ...]]

Build-matrix tool: compiles C/C++ targets with multiple variant configurations.

options:
  --target TARGET              Path to a .cpp file, folder, or CMake project root
  --project PROJECT            Path to an anvil_project.json or anvil.project.json file/folder
  --variants VARIANTS          Path to an anvil_variants.json or anvil.variants.json file/folder
  --clean                      Clean build directories before building
  --stop-on-error              Stop on first variant failure
  --jobs JOBS, -j JOBS         Compile jobs per variant (0 = nproc)
  --parallel PARALLEL, -p      Variants to build in parallel
  --verbose, -v                Print full compilation commands
  --extra-args [...]           Extra compiler/linker arguments (direct mode only)
```

## Examples

See the `examples/` directory for sample configurations.

### Single-file benchmark

```bash
python -m anvil --target benchmark.cpp \
  --variants examples/anvil_variants_full.json \
  --parallel 4 --jobs 2
```

### CMake project with custom environment

```bash
python -m anvil --target myproject \
  --project myproject/anvil_project.json \
  --variants myproject/anvil_variants_quick.json \
  --clean
```

### Verbose output with stop-on-error

```bash
python -m anvil --target src/ --verbose --stop-on-error
```

## Output

Artifacts are collected under `out_dir` (default: `.out/anvil_build/<name>`):

```
.out/anvil_build/myproject/
  ├── myproject__gcc_O0
  ├── myproject__gcc_O1
  ├── myproject__gcc_O2
  ├── myproject__gcc_O3
  ├── myproject__gcc_Ofast
  ├── myproject__gcc_O0.json        # Metadata
  ├── myproject__gcc_O1.json
  ├── myproject__gcc_O2.json
  ├── myproject__gcc_O3.json
  ├── myproject__gcc_Ofast.json
  └── build_summary.json            # Build stats
```

Each `.json` file contains:
- Variant name and configuration
- Compiler used
- Effective flags and defines
- Build directory
- Artifact path

## Testing & CI

- Pytest suite covers direct mode and CMake mode, including positive and negative build paths.
- CMake tests validate config-specific flag behavior for standard and custom build types.
- GitHub Actions runs a cross-platform matrix (Ubuntu, Windows, macOS) and multiple Python versions.

## License

MIT — see [LICENSE](LICENSE)

## Contributing

Contributions welcome! Please open issues and PRs on GitHub.
