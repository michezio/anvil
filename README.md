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
- **Focused workflows**: Select variants by exact name or glob, inspect plans, and resume matching builds
- **Config discovery**: Looks for project config files named `anvil_project.json` or `anvil.project.json`, and variant files named `anvil_variants.json` or `anvil.variants.json` near the target or project directory
- **Reproducible output**: Atomic summaries, hashed manifests, compilation databases, and tool metadata
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
  ├── build_summary.json
  └── manifest.json
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
    "source_dir": ".",
    "target": "my_target",
    "build_type": "Release",
    "toolchain_file": "toolchains/sdk.cmake",
    "artifact": "bin/my_target",
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
| `cmake.source_dir` | string | project config directory | CMake source root, resolved relative to the project config |
| `cmake.target` | string | `""` | CMake target name (required for CMake mode) |
| `cmake.build_type` | string | `""` | Single build type used for both CMake configuration (`CMAKE_BUILD_TYPE`) and target build selection (`cmake --build --config`). If unset, Anvil falls back to `Release`. |
| `cmake.toolchain_file` | string | `""` | Toolchain file resolved relative to the project config |
| `cmake.artifact` | string | `""` | Optional artifact path relative to the variant build directory |
| `cmake.args` | array | `[]` | Extra `cmake` configure arguments |
| `env_setup` | string | `""` | Script to source before building |
| `include_dirs` | array | `[]` | Extra `-I` paths (direct mode) |
| `link_flags` | string | `""` | Extra linker flags |
| `jobs` | int | `0` | Compile jobs per variant (`0` = auto via Python CPU count) |
| `parallel_variants` | int | `1` | Number of direct or CMake variants to build simultaneously; the job budget is divided among CMake workers |
| `stop_on_error` | bool | `false` | Abort on first variant failure |
| `resume` | bool | `false` | Reuse successful builds with matching fingerprints and artifact hashes |
| `clean` | bool | `false` | Clean build directories before building |
| `verbose` | bool | `false` | Print full compiler commands |

### CMake Flag Behavior (Config-Aware)

In CMake mode, Anvil computes separate language payloads. Shared `defines` apply to both languages; `c_flags`/`c_defines` and `cxx_flags`/`cxx_defines` apply only to their language. `standard` configures CMake's required C++ standard.

- **Standard configs** (`Debug`, `Release`, `RelWithDebInfo`, `MinSizeRel`):
  Anvil **appends** injected flags to existing CMake/toolchain defaults.
  This preserves defaults like release-style optimization and `NDEBUG`.
  For standard configs only, Anvil runs a preliminary CMake configure pass to gather existing config flags before appending.

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
| `c_compiler` | string | environment/default C compiler | C compiler command |
| `cxx_compiler` | string | `compiler` | Explicit C++ compiler command |
| `standard` | string | `c++23` | C++ standard flag (for example `c++20` or `c++23`) |
| `c_flags` | array | `[]` | C-only compiler flags |
| `cxx_flags` | array | `[]` | Base compiler flags |
| `defines` | array | `[]` | Shared preprocessor defines |
| `c_defines` | array | `[]` | C-only preprocessor defines |
| `cxx_defines` | array | `[]` | C++-only preprocessor defines |
| `allow_failure` | bool | `false` | Report a failed experimental variant without failing the matrix |

Variant fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Variant identifier |
| `base` | string | unset | Optional base name to inherit from |
| `compiler` | string | inherited / `g++` | Compiler command |
| `c_compiler` | string | inherited | C compiler command |
| `cxx_compiler` | string | inherited / `compiler` | Explicit C++ compiler command |
| `standard` | string | inherited / `c++23` | C++ standard flag |
| `c_flags` | array | `[]` | C-only flags appended to base flags |
| `cxx_flags` | array | `[]` | Variant flags appended to base flags |
| `defines` | array | `[]` | Shared defines appended to base defines |
| `c_defines` | array | `[]` | C-only defines appended to base defines |
| `cxx_defines` | array | `[]` | C++-only defines appended to base defines |
| `allow_failure` | bool | inherited / `false` | Allow this variant to fail without failing the matrix |

## Command Line

```
usage: anvil [-h] [--target TARGET] [--project PROJECT] [--variants VARIANTS]
             [--variant VARIANT] [--match MATCH] [--list-variants] [--dry-run]
             [--clean | --no-clean] [--stop-on-error | --no-stop-on-error]
             [--resume | --no-resume] [--jobs JOBS] [--parallel PARALLEL]
             [--verbose | --no-verbose] [--extra-args [EXTRA_ARGS ...]]

Build-matrix tool: compiles C/C++ targets with multiple variant configurations.

options:
  --target TARGET              Path to a .cpp file, folder, or CMake project root
  --project PROJECT            Path to an anvil_project.json or anvil.project.json file/folder
  --variants VARIANTS          Path to an anvil_variants.json or anvil.variants.json file/folder
  --variant VARIANT            Select an exact variant; repeatable
  --match MATCH                Select variants with a shell-style glob; repeatable
  --list-variants              List expanded, filtered variants without building
  --dry-run                    Print the resolved build plan without building
  --clean, --no-clean          Override build-directory cleaning
  --stop-on-error, --no-stop-on-error
  --resume, --no-resume        Reuse fingerprint-compatible successful builds
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
  ├── myproject__gcc_O3.compile_commands.json
  ├── build_summary.json            # Incrementally written variant results
  └── manifest.json                 # Authoritative current artifacts and SHA-256 hashes
```

Each `.json` file contains:
- Variant name and configuration
- Compiler used
- Effective flags and defines
- Build directory
- Artifact path

Consumers should enumerate `manifest.json`, not files by glob. A new invocation removes
stale files for the active target, and interruption leaves `complete: false` with all
results persisted up to that point.

## Testing & CI

- Pytest suite covers direct mode and CMake mode, including positive and negative build paths.
- CMake tests validate config-specific flag behavior for standard and custom build types.
- GitHub Actions runs a cross-platform matrix (Ubuntu, Windows, macOS) and multiple Python versions.

## License

MIT — see [LICENSE](LICENSE)

## Contributing

Contributions welcome! Please open issues and PRs on GitHub.
