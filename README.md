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
.out/anvil_build/myapp/
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

Create a variants file such as `anvil_variants_quick.json` (the repository examples use the same underscore-based naming):

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
| `cmake.build_type` | string | `Release` | CMake build type used in CMake mode |
| `cmake.args` | array | `[]` | Extra `cmake` configure arguments |
| `env_setup` | string | `""` | Script to source before building |
| `include_dirs` | array | `[]` | Extra `-I` paths (direct mode) |
| `link_flags` | string | `""` | Extra linker flags |
| `jobs` | int | `0` | Compile jobs per variant (`0` = auto via `nproc`) |
| `parallel_variants` | int | `1` | Number of variants to build simultaneously |
| `stop_on_error` | bool | `false` | Abort on first variant failure |
| `clean` | bool | `false` | Clean build directories before building |
| `verbose` | bool | `false` | Print full compiler commands |

### Variants JSON

Anvil reads a top-level JSON array of variant objects. The file can be named `anvil_variants.json` or `anvil.variants.json`, or passed explicitly via `--variants`.

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
| `compiler` | string | `g++` | Compiler command (supports multi-word forms like `zig c++`) |
| `standard` | string | `c++23` | C++ standard flag (for example `c++20` or `c++23`) |
| `cxx_flags` | string | `""` | Compiler flags (for example `-O3 -march=native`) |
| `defines` | array | `[]` | Preprocessor defines (for example `["NDEBUG", "MY_FLAG=1"]`) |

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
  ├── myproject__o2_gcc
  ├── myproject__o3_gcc
  ├── myproject__ofast_gcc
  ├── myproject__o2_gcc.json        # Metadata
  ├── myproject__o3_gcc.json
  ├── myproject__ofast_gcc.json
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
