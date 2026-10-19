"""Build the offline interview map from explicit, symbol-checked source references."""

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MODULES = (
    "auth",
    "datasets",
    "queries",
    "refresh-http",
    "refresh-worker",
    "refresh-execution",
    "frontend-architecture",
    "frontend-auth",
    "frontend-overview",
    "frontend-explorer",
    "frontend-queries",
    "frontend-refresh",
)


def resolve_symbol(source: str, symbol: str) -> tuple[int, int]:
    scope: ast.AST = ast.parse(source)
    for part in symbol.split("."):
        matches = [
            child
            for child in ast.iter_child_nodes(scope)
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name == part
        ]
        if len(matches) != 1:
            raise ValueError(f"Cannot resolve {symbol}")
        scope = matches[0]
    if not isinstance(scope, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError(f"Not a source symbol: {symbol}")
    assert scope.end_lineno is not None
    return min(
        [scope.lineno] + [d.lineno for d in scope.decorator_list]
    ), scope.end_lineno


def build_module(module: str, frontend_root: Path) -> str:
    data = json.loads((HERE / f"{module}.json").read_text(encoding="utf-8"))
    catalog = {
        name: json.loads((HERE / f"{name}.json").read_text(encoding="utf-8"))
        for name in MODULES
    }
    data["navigation"] = [item["module"] for item in catalog.values()]
    flow_ids = [flow["id"] for flow in data["flows"]]
    assert len(flow_ids) == len(set(flow_ids)), "Duplicate flow IDs"
    sources = {}
    frontend = data["module"].get("source") == "frontend"
    source_root = frontend_root.resolve() if frontend else ROOT
    allowed = source_root / ("src" if frontend else "src/outage_explorer")
    ranges = {}
    if frontend:
        result = subprocess.run(
            ["node", str(HERE / "resolve-typescript.cjs"), str(source_root)],
            input=json.dumps(data["nodes"]),
            text=True,
            capture_output=True,
            check=True,
        )
        ranges = json.loads(result.stdout)
    for node_id, node in data["nodes"].items():
        path = node["file"]
        source_path = (source_root / path).resolve()
        if not source_path.is_relative_to(allowed):
            raise ValueError(
                f"Source reference must stay in the product source tree: {path}"
            )
        source = source_path.read_text(encoding="utf-8")
        sources[path] = source
        node["line"], node["end"] = (
            ranges[node_id] if frontend else resolve_symbol(source, node["symbol"])
        )
        for type_id in node.get("types", []):
            assert type_id in data["nodes"], type_id
        for link in node.get("links", []):
            assert link in data["nodes"], link
        for view in node.get("views", []):
            assert any(flow["id"] == view for flow in data["flows"]), view
        for handoff in node.get("handoffs", []):
            target = catalog[handoff["module"]]
            assert any(flow["id"] == handoff["view"] for flow in target["flows"])
    for flow in data["flows"]:
        if flow.get("layout") == "conceptual":
            assert not flow["nodes"] and not flow["edges"], "Overview must be code-free"
            assert flow["heading"] and flow["lanes"] and flow["boundaries"]
            for lane in flow["lanes"]:
                assert lane["view"] in flow_ids and lane["view"] != flow["id"]
                assert len(lane["steps"]) >= 2
                assert all(
                    step["actor"] and step["title"] and step["text"]
                    for step in lane["steps"]
                )
                for step in lane["steps"]:
                    link = step["code"]
                    target = catalog[link["module"]]
                    assert link["node"] in target["nodes"], link
                    assert any(
                        view["id"] == link["view"]
                        and view.get("layout") != "conceptual"
                        for view in target["flows"]
                    ), link
        assert all(node in data["nodes"] for node in flow["nodes"])
        assert all(
            a in flow["nodes"] and b in flow["nodes"] for a, b, _ in flow["edges"]
        )
        if flow.get("layout") == "tree":
            assert len(flow["positions"]) == len(flow["nodes"])
        for choice in flow.get("choices", []):
            assert choice["view"] in flow_ids
        if "pathChooser" in flow:
            assert flow["pathChooser"] in flow_ids
        if flow.get("layout") == "layers":
            displayed = [
                node for row in flow["rows"] for node in (row["caller"], row["callee"])
            ] + flow.get("tail", [])
            assert displayed == flow["nodes"], "Layer reading order must match nodes"
            assert len(displayed) == len(set(displayed)), "Duplicate layer node"
            assert all(
                data["nodes"][row["caller"]]["layer"] == "Application"
                and data["nodes"][row["callee"]]["layer"] == "Infrastructure"
                for row in flow["rows"]
            ), "Layer columns must match source roles"
            for row in flow["rows"]:
                if "view" in row:
                    assert row["view"] in flow_ids
            if "node" in flow["entry"]:
                assert flow["entry"]["node"] in data["nodes"]
            if "resume" in flow:
                assert flow["resume"]["view"] in flow_ids
    data["sources"] = sources
    data["root"] = str(source_root)
    data["language"] = "typescript" if frontend else "python"
    reachable = {node for flow in data["flows"] for node in flow["nodes"]}
    pending = list(reachable)
    while pending:
        node = data["nodes"][pending.pop()]
        for target in node.get("types", []) + node.get("links", []):
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    assert reachable == set(data["nodes"]), "Unreachable source references"
    data["fingerprint"] = hashlib.sha256(
        json.dumps(sources, sort_keys=True).encode()
    ).hexdigest()[:12]
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    template = (HERE / "template.html").read_text(encoding="utf-8")
    assert template.count("/*__MODULE_DATA__*/") == 1
    print(
        f"Validated {module}: {len(data['flows'])} views, {len(data['nodes'])} symbols, "
        f"{len(sources)} source files; snapshot {data['fingerprint']}"
    )
    return template.replace("/*__MODULE_DATA__*/", payload)


def build(check: bool = False, frontend_root: Path = ROOT.parent / "outage-explorer-web") -> int:
    # Resolve every reference before replacing any previously usable artifact.
    outputs = {
        f"{module}.html": build_module(module, frontend_root) for module in MODULES
    }
    outputs["index.html"] = (HERE / "index-template.html").read_text(encoding="utf-8")
    outputs["frontend.html"] = (HERE / "frontend-index-template.html").read_text(
        encoding="utf-8"
    )
    stale = []
    for name, content in outputs.items():
        path = HERE / name
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            path.write_text(content, encoding="utf-8")
    if stale:
        print("Rebuild stale artifacts: " + ", ".join(stale), file=sys.stderr)
        return 1
    print(
        "All snapshots are current."
        if check
        else "Built offline interview walkthrough."
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Reject stale generated pages without writing",
    )
    parser.add_argument(
        "--frontend-root", type=Path, default=ROOT.parent / "outage-explorer-web",
        help="Frontend checkout containing src and installed TypeScript",
    )
    args = parser.parse_args()
    raise SystemExit(build(args.check, args.frontend_root))
