import argparse
import sys
from collections.abc import Sequence

from outage_explorer.application.errors import VerificationError
from outage_explorer.application.services.evidence import VerifyBaseline


def run(service: VerifyBaseline, argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=f"verify-{service.grain}-data",
        description=f"Replay recorded September 2026 {service.grain} evidence offline.",
    )
    parser.add_argument(
        "--evidence-bundle",
        default=f"data/verification/{service.grain}-2026-09/manifest.json",
        help="Evidence manifest (default: repository baseline; run from repository root)",
    )
    parser.add_argument(
        "--output-directory", default=f"build/{service.grain}-verification"
    )
    args = parser.parse_args(argv)
    try:
        result = service.run(args.evidence_bundle, args.output_directory)
    except VerificationError as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    print(f"JSON: {result.json}\nMarkdown: {result.markdown}")
    return 0
