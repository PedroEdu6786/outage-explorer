"""Run the independently supervised refresh composition with explicit shutdown."""

from outage_explorer.application.ports.refresh_execution import RefreshProcess


def run(process: RefreshProcess) -> int:
    try:
        return process.run()
    finally:
        process.close()
