"""Record an operator's explicit local containment review of actual-host reports.

Never enables the API, fetches data or claims full capacity acceptance. Run only
after reading the reports and accepting the documented local limits.
"""

import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import date
from pathlib import Path

from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.infrastructure.sql_validation.configuration import (
    InspectionReview,
    read_inspection_config,
)
from outage_explorer.infrastructure.worker_runtime.configuration import (
    RuntimeEvidence,
    read_runtime_config,
)

ROOT = Path("/var/lib/outage-runtime-validation")
SOURCE = Path("/opt/outage-runtime-validation")
REQUIRED_GATES = {
    "worker_protocol_and_canonical_output",
    "namespace_network_mount_env_denial",
    "source_replacement_cannot_mutate_staged_input",
    "cpu_memory_process_temp_policy",
    "cpu_quota_throttles_busy_children",
    "temporary_quota_enforcement",
    "memory_quota_enforcement",
    "process_quota_and_descendant_reap",
    "deadline_crash_io_cleanup",
    "failed_reap_preserves_slot_pins_and_recovers",
    "restart_reconciles_owned_container",
    "ambiguous_create_and_daemon_failure",
    "disk_spill_readiness_requires_supported_backend",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_report(path):
    cases = list(ET.parse(path).iter("testcase"))
    if not cases:
        raise ValueError("Test report has no cases")
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            raise ValueError("Test report contains failures")
        if case.find("skipped") is not None:
            raise ValueError("Required test was skipped")
    return {"sha256": digest(path), "cases": len(cases)}


def collect_runtime_reports(paths, identity):
    reports, passed = [], set()
    for path in paths:
        value = json.loads(path.read_text())
        if value.get("profile_identity") != identity or not value.get("gates"):
            raise ValueError("Runtime report identity/gates mismatch")
        for name, gate in value["gates"].items():
            status = gate["status"]
            if status == "failed" or status not in {"passed", "not_run", "unsupported"}:
                raise ValueError("Runtime report contains failed gate")
            if status == "passed":
                passed.add(name)
            elif name not in {
                "disk_quota",
                "cpu_quota_throttles_busy_children",
                "cpu_load_probe",
            }:
                raise ValueError("Required runtime gate did not pass")
        if (
            value["gates"].get("identity", {}).get("status") != "passed"
            or value["gates"].get("cleanup", {}).get("status") != "passed"
        ):
            raise ValueError("Runtime identity/cleanup did not pass")
        reports.append({"name": path.name, "sha256": digest(path)})
    if not REQUIRED_GATES <= passed:
        raise ValueError("Required containment reports missing")
    return reports


def write_private(path, document):
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        json.dump(document, stream, indent=2, default=str)
        stream.write("\n")


def review(reviewer):
    profile, _ = read_runtime_config(ROOT / "candidate.json")
    parser, _ = read_inspection_config(ROOT / "parser-candidate.json")
    outputs = [
        ROOT / name
        for name in (
            "local-scope-review.json",
            "runtime-reviewed.json",
            "parser-reviewed.json",
        )
    ]
    if any(path.exists() for path in outputs):
        raise ValueError("Review output already exists; preserve previous evidence")
    controlled = test_report(ROOT / "controlled.xml")
    native_parser = test_report(ROOT / "parser.xml")
    native_worker = test_report(ROOT / "docker.xml")
    reports = collect_runtime_reports(
        sorted((ROOT / "owned/validation-reports").glob("*.json")), profile.identity
    )
    inspector = parser.build()
    try:
        inspector.start()
        if not inspector.inspect("SELECT 1").reference_free:
            raise ValueError("Parser scope verification failed")
        for sql in (
            "DELETE FROM national",
            "SELECT * FROM read_parquet('/not-authorized')",
        ):
            try:
                inspector.inspect(sql)
            except SqlRejected:
                continue
            raise ValueError("Parser rejection verification failed")
    finally:
        inspector.close()
    source_hashes = {
        str(path.relative_to(SOURCE)): digest(path)
        for folder in ("src", "scripts", "tests")
        for path in sorted((SOURCE / folder).rglob("*.py"))
    }
    summary = {
        "scope": "local-preview-sql",
        "profile_identity": profile.identity,
        "parser_profile_identity": parser.identity,
        "reviewer": reviewer,
        "reviewed_on": date.today(),
        "controlled": controlled,
        "native_parser": native_parser,
        "native_worker": native_worker,
        "containment_reports": reports,
        "parser_exact_profile_smoke": "passed",
        "source_files_sha256": source_hashes,
        "refresh": "idle",
        "capacity_measurements": "deferred; not measured or accepted by this record",
        "external_services": "operator configured; not verified by this command",
    }
    write_private(outputs[0], summary)
    summary_digest = digest(outputs[0])
    # The same scope summary binds containment/termination/storage reports. Its
    # measurement field explicitly records deferral, never a measured result.
    evidence = RuntimeEvidence(
        profile.identity,
        controlled["sha256"],
        summary_digest,
        summary_digest,
        summary_digest,
        summary_digest,
        reviewer,
        date.today(),
        "local-preview-sql",
    )
    parser_review = InspectionReview(
        parser.identity, controlled["sha256"], summary_digest, reviewer, date.today()
    )
    write_private(
        outputs[1], {"profile": asdict(profile), "evidence": asdict(evidence)}
    )
    write_private(
        outputs[2], {"profile": asdict(parser), "evidence": asdict(parser_review)}
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reviewer",
        required=True,
        help="Your name, after personally reviewing the reports",
    )
    parser.add_argument(
        "--accept-local-containment",
        action="store_true",
        help="Explicitly accept initial local limits with refresh idle; does not start the API",
    )
    args = parser.parse_args(argv)
    if not args.accept_local_containment or not args.reviewer.strip():
        parser.error("Read the reports and explicitly accept local containment first")
    if sys.platform != "linux" or os.getuid() != 65534:
        parser.error("Run as the configured controller on the Linux daemon host")
    try:
        review(args.reviewer.strip())
    except Exception:
        parser.exit(
            1,
            "Review not recorded: check actual reports, matching identities, parser and unused output paths.\n",
        )
    print(
        "Local review recorded. API and refresh remain stopped; full capacity acceptance is deferred."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
