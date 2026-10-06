"""Partial real analytical measurements; never claims refresh/API/S3 coverage."""

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from tests.runtime_validation import (
    RuntimeHarness,
    measured_workload,
    read_representative_inputs,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument(
        "--include-previews",
        action="store_true",
        help="Also verify all-grain native previews/continuation/changed-date filters",
    )
    args = parser.parse_args()
    harness = RuntimeHarness(
        Path("/var/lib/outage-runtime-validation/candidate.json"),
        Path("/usr/bin/docker"),
    )
    report_path = Path("/var/lib/outage-runtime-validation") / (
        "analytical-only-" + uuid4().hex + ".json"
    )
    status = "failed"
    stage = "startup"
    bounds = {"request_bytes_limit": harness.profile.request_bytes}

    def trace(frame, event, arg):
        # Inspect numeric sizes only at the production controller's fixed boundary.
        # No arguments/paths/payload contents enter reports; enforcement is unchanged.
        if event == "exception" and frame.f_code.co_name == "_create_arguments":
            arguments = frame.f_locals.get("args", ())
            bounds["mount_argv_bytes"] = sum(len(a.encode()) + 1 for a in arguments)
        if event == "exception" and frame.f_code.co_name == "_run":
            bounds["worker_request_bytes"] = len(frame.f_locals.get("data", b""))
            bounds["staged_files"] = len(frame.f_locals.get("files", ()))
        return trace

    try:
        harness.open()
        stage = "inputs"
        inputs = read_representative_inputs(
            args.inputs, harness.profile, analytical_only=True
        )
        harness.report.document["workload_identity"] = inputs.identity
        harness.report.gate("representative_inputs", "passed")
        stage = "workload"
        sys.settrace(trace)
        try:
            metrics = measured_workload(
                harness,
                inputs,
                analytical_only=True,
                include_previews=args.include_previews,
            )
        finally:
            sys.settrace(None)
        status = (
            "passed"
            if metrics["samples"]
            and not metrics["sampling_failures"]
            and metrics["container_memory_peak_bytes"]
            and metrics["sampled_container_count"]
            == (33 if args.include_previews else 6)
            else "failed"
        )
        harness.report.document["resource_sampler"] = "docker-api-v1.51-one-shot"
        harness.report.document["container_memory_basis"] = (
            "total-cgroup-usage-including-cache"
        )
        harness.report.document["resource_observation"] = (
            "sampled-not-complete-high-water"
        )
        harness.report.gate("analytical_only_measurements", status, metrics)
    except Exception as error:
        # Safe bounded failure evidence, never exception text or private diagnostics.
        harness.report.gate("analytical_only_measurements", "failed")
        harness.report.document["failure_stage"] = stage
        harness.report.document["failure_class"] = (
            type(error).__name__
            if type(error).__name__
            in {
                "ValueError",
                "OSError",
                "RuntimeUnavailableError",
                "AnalyticalResourceError",
                "AnalyticalExecutionError",
                "KeyError",
            }
            else "other"
        )
        harness.report.document["failure_reason"] = (
            "mount_argument_limit"
            if str(error) == "Analytical mount argument limit exceeded"
            else "other"
        )
        harness.report.gate("controller_bounds", "failed", bounds)
    finally:
        try:
            harness.close()
            harness.report.gate("cleanup", "passed")
        except Exception:
            harness.report.gate("cleanup", "failed")
            status = "failed"
        for gate in (
            "representative_measurements",
            "refresh_api_overlap",
            "external_refresh_transfer",
            "product_s3_cold_cache",
        ):
            harness.report.gate(gate, "not_run")
        digest = harness.report.write(report_path)
        print(
            json.dumps(
                {
                    "report_name": report_path.name,
                    "report_sha256": digest,
                    "status": status,
                    "readiness": "unreviewed",
                }
            )
        )
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
