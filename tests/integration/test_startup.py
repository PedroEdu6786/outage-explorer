import subprocess
import sys
import textwrap


def test_imports_and_factory_do_not_start_work():
    # A fresh interpreter prevents cached imports from concealing side effects.
    script = textwrap.dedent("""
        import importlib
        import pkgutil
        import sys
        from unittest.mock import patch
        from flask import Flask

        def forbid_external_work(event, args):
            if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system", "os.fork"}:
                raise AssertionError(f"Unexpected startup work: {event}")

        sys.addaudithook(forbid_external_work)
        with patch("threading.Thread.start", side_effect=AssertionError("Thread started")):
            with patch.object(Flask, "__init__", side_effect=AssertionError("Import created an app")), patch("pathlib.Path.mkdir", side_effect=AssertionError("Import touched storage")):
                import outage_explorer
                for module in pkgutil.walk_packages(outage_explorer.__path__, "outage_explorer."):
                    importlib.import_module(module.name)

            from outage_explorer.infrastructure.recorded_evidence import LocalRecordedEvidence
            from outage_explorer.infrastructure.verification_report import LocalReportWriter
            with patch.object(LocalRecordedEvidence, "load", side_effect=AssertionError("Construction loaded evidence")):
                with patch.object(LocalReportWriter, "write", side_effect=AssertionError("Construction wrote report")):
                    from outage_explorer.bootstrap import build_national_verifier, build_facility_verifier, build_generator_verifier
                    assert build_national_verifier() is not None
                    assert build_facility_verifier() is not None
                    assert build_generator_verifier() is not None

            from outage_explorer.infrastructure.clock import SystemClock
            from outage_explorer.entrypoints.http.startup import create_app
            with patch.object(SystemClock, "now", side_effect=AssertionError("Factory ran probe")), patch("outage_explorer.bootstrap.execute_connector", side_effect=AssertionError("Connector started")), patch("outage_explorer.infrastructure.eia.source.EiaSource.__init__", side_effect=AssertionError("EIA constructed")), patch("outage_explorer.infrastructure.parquet.storage.LocalParquetStore.__init__", side_effect=AssertionError("Storage constructed")):
                from outage_explorer.entrypoints.cli.connector_startup import main
                with patch.object(sys, "argv", ["build-connector-candidate", "--help"]):
                    try:
                        main()
                    except SystemExit as error:
                        assert error.code == 0
                app = create_app()
            assert app.test_client().get("/health").status_code == 200
    """)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
