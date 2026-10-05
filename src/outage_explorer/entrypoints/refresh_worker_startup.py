from outage_explorer.bootstrap import build_refresh_worker
from outage_explorer.entrypoints.refresh_worker import run


def main() -> int:
    return run(build_refresh_worker())


if __name__ == "__main__":
    raise SystemExit(main())
