"""Restricted worker transport seam; bootstrap supplies the reviewed executor."""

from collections.abc import Callable

from outage_explorer.application.ports.execution import PreviewRead, PreviewRows


def run_preview(
    request: PreviewRead, execute: Callable[[PreviewRead], PreviewRows]
) -> PreviewRows:
    return execute(request)
