import json
from pathlib import Path

from .defaults import DEFAULT_VARIANTS_DATA
from .models import BuildVariant, ProjectConfig


def discover_configs(
    target_path: Path,
    *,
    base_dir: Path | None = None,
    project_config_path: Path | None = None,
    variants_config_path: Path | None = None,
) -> tuple[Path | None, Path | None]:
    """Look for project/variant config files near the target, the project config, and the working directory."""
    search_dirs: list[Path] = []
    if target_path.is_file():
        search_dirs.append(target_path.parent)
    elif target_path.exists():
        search_dirs.append(target_path)

    if project_config_path is not None:
        resolved_project_config = project_config_path.resolve(strict=False)
        if resolved_project_config.parent.exists():
            search_dirs.append(resolved_project_config.parent)

    if variants_config_path is not None:
        resolved_variants_config = variants_config_path.resolve(strict=False)
        if resolved_variants_config.parent.exists():
            search_dirs.append(resolved_variants_config.parent)

    if base_dir is not None:
        search_dirs.append(base_dir)

    seen: set[Path] = set()
    for search_dir in search_dirs:
        resolved_dir = search_dir.resolve(strict=False)
        if resolved_dir in seen:
            continue
        seen.add(resolved_dir)

        project_json = next(
            (resolved_dir / name for name in ("anvil_project.json", "anvil.project.json") if (resolved_dir / name).exists()),
            None,
        )
        variants_json = next(
            (resolved_dir / name for name in ("anvil_variants.json", "anvil.variants.json") if (resolved_dir / name).exists()),
            None,
        )
        if project_json is not None or variants_json is not None:
            return project_json, variants_json

    return None, None


def parse_project_config(path: Path) -> ProjectConfig:
    data = json.loads(path.read_text(encoding="utf-8"))

    name = str(data.get("name", path.parent.name)).strip()
    build_dir = str(data.get("build_dir", f"/build/anvil/{name}")).strip()
    out_dir = str(data.get("out_dir", f".out/anvil_build/{name}")).strip()

    cmake_section = data.get("cmake")
    if isinstance(cmake_section, dict):
        cmake_target = str(cmake_section.get("target", data.get("cmake_target", ""))).strip()
        cmake_build_type = str(cmake_section.get("build_type", data.get("build_type", ""))).strip()
        cmake_args_raw = cmake_section.get("args", data.get("cmake_args", []))
    else:
        cmake_target = str(data.get("cmake_target", "")).strip()
        cmake_build_type = str(data.get("build_type", "")).strip()
        cmake_args_raw = data.get("cmake_args", [])

    if not isinstance(cmake_args_raw, list):
        raise ValueError("'cmake.args' must be a list")
    cmake_args = tuple(str(v) for v in cmake_args_raw)

    env_setup = str(data.get("env_setup", "")).strip()

    include_dirs_raw = data.get("include_dirs", [])
    if not isinstance(include_dirs_raw, list):
        raise ValueError("'include_dirs' must be a list")
    include_dirs = tuple(str(d).strip() for d in include_dirs_raw)
    link_flags = str(data.get("link_flags", "")).strip()

    jobs = int(data.get("jobs", 0))
    parallel_variants = max(1, int(data.get("parallel_variants", 1)))
    stop_on_error = bool(data.get("stop_on_error", False))
    clean = bool(data.get("clean", False))
    verbose = bool(data.get("verbose", False))

    return ProjectConfig(
        name=name,
        build_dir=build_dir,
        out_dir=out_dir,
        cmake_target=cmake_target,
        cmake_build_type=cmake_build_type,
        cmake_args=cmake_args,
        env_setup=env_setup,
        include_dirs=include_dirs,
        link_flags=link_flags,
        jobs=jobs,
        parallel_variants=parallel_variants,
        stop_on_error=stop_on_error,
        clean=clean,
        verbose=verbose,
    )


def parse_variants(path: Path) -> list[BuildVariant]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Variants JSON must be an object with 'variants' list and optional 'bases' list")
    return _parse_variants_config(data, source=str(path))


def _parse_string_list(raw: object, *, key: str, owner: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{owner} key '{key}' must be a list")
    values: list[str] = []
    for value in raw:
        text = str(value).strip()
        if text:
            values.append(text)
    return tuple(values)


def _parse_base_entry(item: dict, *, source: str, defaults: BuildVariant) -> BuildVariant:
    name = str(item.get("name", "")).strip()
    if not name:
        raise ValueError(f"Base entry in {source} missing non-empty 'name'")

    compiler = str(item.get("compiler", defaults.compiler)).strip() or defaults.compiler
    standard = str(item.get("standard", defaults.standard)).strip() or defaults.standard
    cxx_flags = _parse_string_list(item.get("cxx_flags", []), key="cxx_flags", owner=f"Base '{name}'")
    defines = _parse_string_list(item.get("defines", []), key="defines", owner=f"Base '{name}'")

    return BuildVariant(
        name=name,
        compiler=compiler,
        standard=standard,
        cxx_flags=cxx_flags,
        defines=defines,
    )


def _parse_variants_config(data: dict, source: str = "<builtin>") -> list[BuildVariant]:
    variant_defaults = BuildVariant()

    bases_raw = data.get("bases", [])
    if not isinstance(bases_raw, list):
        raise ValueError(f"'bases' in {source} must be a list")

    variants_raw = data.get("variants")
    if not isinstance(variants_raw, list):
        raise ValueError(f"'variants' in {source} must be a list")

    bases_by_name: dict[str, BuildVariant] = {}
    for item in bases_raw:
        if not isinstance(item, dict):
            raise ValueError(f"Each base entry in {source} must be an object")
        base = _parse_base_entry(item, source=source, defaults=variant_defaults)
        if base.name in bases_by_name:
            raise ValueError(f"Duplicate base name '{base.name}' in {source}")
        bases_by_name[base.name] = base

    variants: list[BuildVariant] = []
    for i, item in enumerate(variants_raw):
        if not isinstance(item, dict):
            raise ValueError(f"Variant entry {i} in {source} must be an object")

        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"Variant entry {i} in {source} missing non-empty 'name'")

        base_name = item.get("base")
        if base_name is not None:
            base_key = str(base_name).strip()
            if not base_key:
                raise ValueError(f"Variant '{name}' has empty 'base' value")
            base = bases_by_name.get(base_key)
            if base is None:
                raise ValueError(f"Variant '{name}' references unknown base '{base_key}' in {source}")
        else:
            base = variant_defaults

        compiler = str(item.get("compiler", base.compiler)).strip() or base.compiler
        standard = str(item.get("standard", base.standard)).strip() or base.standard
        variant_cxx_flags = _parse_string_list(item.get("cxx_flags", []), key="cxx_flags", owner=f"Variant '{name}'")
        variant_defines = _parse_string_list(item.get("defines", []), key="defines", owner=f"Variant '{name}'")

        cxx_flags = base.cxx_flags + variant_cxx_flags
        defines = base.defines + variant_defines

        variants.append(
            BuildVariant(
                name=name,
                compiler=compiler,
                standard=standard,
                cxx_flags=cxx_flags,
                defines=defines,
            )
        )

    return variants


def default_variants() -> list[BuildVariant]:
    return _parse_variants_config(DEFAULT_VARIANTS_DATA)
