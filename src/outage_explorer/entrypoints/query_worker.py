"""Restricted worker transport seam; bootstrap supplies the reviewed executor."""

import json
from collections.abc import Callable
from typing import BinaryIO

from outage_explorer.application.ports.execution import PreviewRead, PreviewRows


def run_preview(
    request: PreviewRead, execute: Callable[[PreviewRead], PreviewRows]
) -> PreviewRows:
    return execute(request)


def run(execute: Callable[[bytes], bytes], source: BinaryIO, target: BinaryIO) -> int:
    """Consume one bounded request, emit one response, then exit."""
    response = execute(source.read(131_072 + 1))
    target.write(response + b"\n")
    target.flush()
    return 1 if "error" in json.loads(response) else 0
