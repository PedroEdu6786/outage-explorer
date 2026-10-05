"""Real engine evidence is deliberately restricted to a controlled child process."""

import json
import subprocess
import sys
from pathlib import Path


def test_pinned_parser_engine_and_lossless_values_in_dedicated_process():
    probe = Path(__file__).parents[1] / "fixtures/data_api/engine_probe.py"
    result = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    evidence = json.loads(result.stdout)
    assert evidence["engine_version"] == "1.5.6"
    assert evidence["queries_verified"] == 16
    assert (
        evidence["encoded"]["columns"][0]["name"]
        == evidence["encoded"]["columns"][1]["name"]
        == "x"
    )
    fixtures = json.loads(
        (Path(__file__).parents[2] / "docs/specs/data-api/fixtures.json").read_text()
    )
    golden = next(
        item["body"]
        for item in fixtures["fixtures"]
        if item["name"] == "query_lossless_types"
    )
    assert evidence["encoded"]["columns"] == golden["columns"]
    assert evidence["encoded"]["rows"] == golden["rows"]
