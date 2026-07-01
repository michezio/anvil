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
- **Auto-discovery**: Find `anvil.project.json` and `anvil.variants.<preset>.json` automatically
- **Flexible output**: Artifacts and metadata collected in a single directory

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

Produces three binaries (O2, O3, Ofast):
```
.out/anvil/myapp/
  ├── myapp__o2_baseline
  ├── myapp__o3_baseline
  ├── myapp__ofast_fastmath
  └── build_summary.json
```

### 2. Compile all files in a folder

```bash
python -m anvil --target src/myproject/
```

### 3. Use custom variants

Create `anvil.variants.quick.json` next to your source:

```json
[
  {
    "name": "gcc_o3",
    "compiler": "g++",
    "standard": "c++23",
    "cxx_flags": "-O3",
    "defines": []
  },
  {
    "name": "clang_o3",
    "compiler": "clang++",
    "standard": "c++23",
    "cxx_flags": "-O3",
    "defines": []
  }
]
```

Then:
```bash
python -m anvil --target src/myapp.cpp
```

### 4. Control build behavior with config files

Create `anvil.project.json` next to your source:

```json
{
  "name": "myproject",
  "out_dir": ".out/myproject",
  "include_dirs": ["/opt/deps/include"],
  "link_flags": "-L/opt/deps/lib -lmydep",
  
  "jobs": 0,
  "parallel_variants": 4,
  "stop_on_error": false,
  "verbose": false
}
```

Then:
```bash
python -m anvil --target src/
```

## Configuration

### `anvil.project.json`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (inferred) | Project name, used in output paths |
| `build_dir` | string | `/build/anvil` | CMake build directory (CMake mode) |
| `out_dir` | string | `.out/anvil/<name>` | Output directory for artifacts |
| `cmake_target` | string | `` | CMake target name (required for CMake mode) |
| `cmake_args` | array | `[]` | Extra `cmake` configure args |
| `env_setup` | string | `` | Script to source before building |
| `include_dirs` | array | `[]` | Extra `-I` paths (direct mode) |
| `link_flags` | string | `` | Extra linker flags |
| `jobs` | int | `0` | Compile jobs per variant (0 = nproc) |
| `parallel_variants` | int | `1` | Number of variants to build simultaneously |
| `stop_on_error` | bool | `false` | Abort on first variant failure |
| `clean` | bool | `false` | Clean build directories before building |
| `verbose` | bool | `false` | Print full compiler commands |

### `anvil.variants.<preset>.json`

Array of variant objects. Example:

```json
[
  {
    "name": "o3_baseline",
    "compiler": "g++",
    "standard": "c++23",
    "cxx_flags": "-O3",
    "defines": ["MY_DEFINE=1"]
  }
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Variant identifier |
| `compiler` | string | `g++` | Compiler command (supports multi-word like `zig c++`) |
| `standard` | string | `c++23` | C++ standard flag (e.g., `c++20`, `c++23`) |
| `cxx_flags` | string | `` | Compiler flags (e.g., `-O3 -march=native`) |
| `defines` | array | `[]` | Preprocessor defines (e.g., `["NDEBUG", "MY_FLAG=1"]`) |

## Command Line

```
usage: anvil [-h] [--target TARGET] [--project-config PROJECT_CONFIG]
             [--variants VARIANTS] [--preset PRESET]
             [--build-type {Release,Debug,MinSizeRel,RelWithDebInfo}]
             [--clean] [--stop-on-error] [--jobs JOBS] [--parallel PARALLEL]
             [--verbose] [--extra-args [EXTRA_ARGS ...]]

Build-matrix tool: compiles C/C++ targets with multiple variant configurations.

options:
  --target TARGET              Path to .cpp file or folder
  --project-config PATH        Explicit project JSON config
  --variants PATH              Explicit variants JSON path
  --preset PRESET              Variant preset name (default: quick)
  --build-type {Release,Debug,MinSizeRel,RelWithDebInfo}
                               CMake build type (cmake mode only)
  --clean                      Clean build dirs before building
  --stop-on-error              Stop on first variant failure
  --jobs JOBS, -j JOBS         Compile jobs per variant (0 = nproc)
  --parallel PARALLEL, -p      Variants to build in parallel
  --verbose, -v                Print full compilation commands
  --extra-args [...]           Extra compiler/linker arguments
```

## Examples

See the `examples/` directory for sample configurations.

### Single-file benchmark

```bash
python -m anvil --target benchmark.cpp \
  --variants examples/anvil.variants.full.json \
  --parallel 4 --jobs 2
```

### CMake project with custom environment

```bash
python -m anvil --project-config myproject/anvil.project.json \
  --variants myproject/anvil.variants.quick.json \
  --build-type Release --clean
```

### Verbose output with stop-on-error

```bash
python -m anvil --target src/ --verbose --stop-on-error
```

## Output

Artifacts are collected under `out_dir` (default: `.out/anvil/<name>`):

```
.out/anvil/myproject/
  ├── myproject__o2_gcc
  ├── myproject__o3_gcc
  ├── myproject__ofast_clang
  ├── myproject__o2_gcc.json        # Metadata
  ├── myproject__o3_gcc.json
  ├── myproject__ofast_clang.json
  └── build_summary.json            # Build stats
```

Each `.json` file contains:
- Variant name and configuration
- Compiler used
- Effective flags and defines
- Build directory
- Artifact path

## License

MIT — see [LICENSE](LICENSE)

## Contributing

Contributions welcome! Please open issues and PRs on GitHub.
