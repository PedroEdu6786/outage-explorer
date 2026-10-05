"""Static guardrails, not a proof of runtime purity or sandbox security."""

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = "outage_explorer"
STARTUP = f"{ROOT}.entrypoints.http.startup"
STARTUP_SOURCE = """
from flask import Flask
from outage_explorer.bootstrap import build_http_app

def create_app() -> Flask:
    return build_http_app()
"""
CLI_STARTUP = f"{ROOT}.entrypoints.cli.startup"
CLI_STARTUP_SOURCE = """
from outage_explorer.bootstrap import build_national_verifier
from outage_explorer.entrypoints.cli.command import run

def main() -> int:
    return run(build_national_verifier())

if __name__ == "__main__":
    raise SystemExit(main())
"""
CONNECTOR_STARTUP_SOURCE = """
from outage_explorer.bootstrap import execute_connector, execute_connector_artifacts, execute_connector_to_s3
from outage_explorer.entrypoints.cli.connector import run

def main() -> int:
    return run(execute_connector, execute_artifacts=execute_connector_artifacts, execute_durable=execute_connector_to_s3)

if __name__ == "__main__":
    raise SystemExit(main())
"""
ACCESS_STARTUP_SOURCE = """
from outage_explorer.bootstrap import execute_access_setup
from outage_explorer.entrypoints.cli.access_setup import run

def main() -> int:
    return run(execute_access_setup)

if __name__ == "__main__":
    raise SystemExit(main())
"""
REFRESH_STARTUP_SOURCE = """
from outage_explorer.bootstrap import build_refresh_worker
from outage_explorer.entrypoints.refresh_worker import run

def main() -> int:
    return run(build_refresh_worker())

if __name__ == "__main__":
    raise SystemExit(main())
"""
CLI_WRAPPERS = {
    f"{ROOT}.entrypoints.refresh_worker_startup": (
        "build_refresh_worker",
        REFRESH_STARTUP_SOURCE,
    ),
    f"{ROOT}.entrypoints.cli.access_startup": (
        "execute_access_setup",
        ACCESS_STARTUP_SOURCE,
    ),
    f"{ROOT}.entrypoints.cli.connector_startup": (
        "execute_connector",
        CONNECTOR_STARTUP_SOURCE,
    ),
    CLI_STARTUP: ("build_national_verifier", CLI_STARTUP_SOURCE),
    **{
        f"{ROOT}.entrypoints.cli.{grain}_startup": (
            f"build_{grain}_verifier",
            CLI_STARTUP_SOURCE.replace(
                "build_national_verifier", f"build_{grain}_verifier"
            ),
        )
        for grain in ("facility", "generator")
    },
}
PURE_IMPORTS = {
    "__future__",
    "abc",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "functools",
    "fractions",
    "itertools",
    "math",
    "operator",
    "re",
    "types",
    "typing",
}
ALLOWED = {
    "domain": ("domain",),
    "application": ("domain", "application"),
    "infrastructure": (
        "domain",
        "application.ports",
        "application.dto",
        "application.errors",
        "infrastructure",
    ),
    "entrypoints": ("application", "entrypoints"),
    "settings": (),
}


def under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def imports(tree: ast.AST, package: str) -> list[tuple[int, str]]:
    """Include imported symbols so `from package import submodule` is checked."""
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, package)
            result.extend((node.lineno, f"{base}.{alias.name}") for alias in node.names)
    return result


def is_startup_wrapper(tree: ast.Module, expected: str = STARTUP_SOURCE) -> bool:
    body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    actual = ast.Module(body=body, type_ignores=[])
    return ast.dump(actual) == ast.dump(ast.parse(expected))


def allowed_dependency(source: str, target: str) -> bool:
    if under(target, STARTUP) or any(
        under(target, wrapper) for wrapper in CLI_WRAPPERS
    ):
        return False  # Startup must never become a service locator or re-export.
    if source == STARTUP and target == f"{ROOT}.bootstrap.build_http_app":
        return True  # Its entire AST is separately constrained to forwarding.
    if source in CLI_WRAPPERS and (
        target == f"{ROOT}.bootstrap.{CLI_WRAPPERS[source][0]}"
        or (
            source == f"{ROOT}.entrypoints.cli.connector_startup"
            and target
            in {
                f"{ROOT}.bootstrap.execute_connector_artifacts",
                f"{ROOT}.bootstrap.execute_connector_to_s3",
            }
        )
    ):
        return True
    layer = source.removeprefix(ROOT + ".").split(".")[0]
    if layer == "bootstrap":
        return True
    if under(target, ROOT):
        return any(
            under(target, f"{ROOT}.{prefix}") for prefix in ALLOWED.get(layer, ())
        )
    if (
        source == f"{ROOT}.application.ports.refresh_execution"
        and target == "contextlib.AbstractContextManager"
    ):
        return True  # Type contract only; no context-manager execution helper.
    # Pure in-memory encoding only; do not admit json file readers to inner layers.
    if source == f"{ROOT}.application.refresh_outcomes" and target == "json.dumps":
        return True
    if source == f"{ROOT}.application.data_payloads" and target == "json.loads":
        return True  # Pure durable-to-public DTO projection; no file readers.
    external = target.split(".")[0]
    if external in {"importlib", "builtins"}:
        return False
    if layer in {"domain", "application"}:
        return external in PURE_IMPORTS
    if layer == "entrypoints":
        # Add reviewed transport dependencies here as new entry points arrive.
        transport = (
            {"argparse", "sys"}
            | ({"logging"} if source == f"{ROOT}.entrypoints.cli.connector" else set())
            if source
            in {
                f"{ROOT}.entrypoints.cli.command",
                f"{ROOT}.entrypoints.cli.connector",
                f"{ROOT}.entrypoints.cli.access_setup",
            }
            else set()
        )
        if source == f"{ROOT}.entrypoints.cli.access_setup":
            transport |= {"json", "pathlib"}
        if source == f"{ROOT}.entrypoints.http.auth_transport":
            transport |= {"logging"}
        if source in {
            f"{ROOT}.entrypoints.http.schemas",
            f"{ROOT}.entrypoints.http.data_schemas",
        }:
            transport |= {"json"}  # Strict transport JSON decoding only.
        if source == f"{ROOT}.entrypoints.http.errors":
            transport |= {"werkzeug"}
        return external in PURE_IMPORTS | {"flask"} | transport
    return layer in {"infrastructure", "settings"}


def cycle_errors(graph: dict[str, set[str]]) -> list[str]:
    visited: set[str] = set()
    active: list[str] = []
    errors: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            errors.append("Import cycle: " + " -> ".join([*active, module]))
            return
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
    return errors


def violations(package_root: Path) -> list[str]:
    modules: dict[str, tuple[Path, ast.Module, str]] = {}
    for path in sorted(package_root.rglob("*.py")):
        parts = list(path.relative_to(package_root.parent).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        module = ".".join(parts)
        package = module if is_package else module.rpartition(".")[0]
        modules[module] = (
            path,
            ast.parse(path.read_text(), filename=str(path)),
            package,
        )

    errors = []
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for module, (path, tree, package) in modules.items():
        if module == STARTUP and not is_startup_wrapper(tree):
            errors.append(f"{module}: startup may only forward to build_http_app")
        if module in CLI_WRAPPERS and not is_startup_wrapper(
            tree, CLI_WRAPPERS[module][1]
        ):
            errors.append(
                f"{module}: startup may only compose the verification command"
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in {"__import__", "exec", "eval"}:
                errors.append(f"{module}:{node.lineno}: dynamic loading is forbidden")
            if (
                isinstance(node, ast.Name)
                and node.id == "open"
                and module.split(".")[1:2] in (["domain"], ["application"])
            ):
                errors.append(
                    f"{module}:{node.lineno}: inner-layer file I/O is forbidden"
                )
        try:
            dependencies = imports(tree, package)
        except (ImportError, ValueError) as error:
            errors.append(f"{module}: invalid relative import: {error}")
            continue
        for line, target in dependencies:
            if target.endswith(".*") or not allowed_dependency(module, target):
                errors.append(
                    f"{path.relative_to(package_root)}:{line}: {module} -> {target}"
                )
            # Find the actual module behind an imported symbol; scanning every
            # initializer also exposes re-exports of forbidden dependencies.
            dependency = target
            while dependency and dependency not in modules:
                dependency = dependency.rpartition(".")[0]
            if dependency and dependency != module:
                graph[module].add(dependency)
    return errors + cycle_errors(graph)
