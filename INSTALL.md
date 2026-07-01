# Installation & Development

## Install for Development (editable)

From the `anvil/` directory:

```bash
pip install -e .
```

Then you can run anvil as:

```bash
# As a module
python -m anvil --target myfile.cpp

# Or directly (if installed with console script)
anvil --target myfile.cpp
```

## Test Installation

```bash
# Verify it works
python -m anvil --help

# Try a quick build
python -m anvil --target examples/sample.cpp
```

## Using from Another Project

### Option 1: Add to PYTHONPATH

```bash
export PYTHONPATH=/path/to/anvil:$PYTHONPATH
python -m anvil --target src/myapp.cpp
```

### Option 2: Install in development mode

```bash
cd /path/to/anvil
pip install -e .

# Then from anywhere:
python -m anvil --target /path/to/myapp.cpp
# or
anvil --target /path/to/myapp.cpp
```

### Option 3: Install from PyPI (future)

```bash
pip install anvil-matrix
anvil --target myapp.cpp
```

## Project Structure

```
anvil/
├── src/                       # Python package
│   ├── __init__.py            # Package init, exports main()
│   ├── __main__.py            # Entry point for python -m anvil
│   └── anvil.py               # Main logic
├── examples/                  # Example configurations
│   ├── anvil.project.json
│   ├── anvil.variants.quick.json
│   └── anvil.variants.full.json
├── pyproject.toml             # Python package metadata
├── README.md                  # User documentation
├── LICENSE                    # MIT license
├── .gitignore                 # Git ignore rules
└── INSTALL.md                 # This file
```

## Preparing for GitHub Release

When you're ready to publish:

1. Update `pyproject.toml`:
   - Change repository URLs to your GitHub repo
   - Bump version if needed

2. Create a `setup.py` (optional, if not using pyproject.toml):
   ```python
   from setuptools import setup
   setup()
   ```

3. Build and upload to PyPI:
   ```bash
   pip install build twine
   python -m build
   twine upload dist/*
   ```

4. Create a GitHub release with tags matching version

## Dependencies

- Python 3.10+
- Standard library only (no external dependencies!)

Anvil uses only:
- `argparse` — CLI parsing
- `json` — Config file parsing
- `subprocess` — Spawning compiler processes
- `pathlib` — Path operations
- `dataclasses` — Config objects
- `concurrent.futures` — Parallel builds
