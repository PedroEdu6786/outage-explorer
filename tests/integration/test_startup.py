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
            with patch.object(SystemClock, "now", side_effect=AssertionError("Factory ran probe")), patch("outage_explorer.bootstrap.execute_connector_to_s3", side_effect=AssertionError("Durable connector started")), patch("outage_explorer.bootstrap.execute_connector", side_effect=AssertionError("Connector started")), patch("boto3.Session", side_effect=AssertionError("AWS session constructed")), patch("outage_explorer.infrastructure.eia.source.EiaSource.__init__", side_effect=AssertionError("EIA constructed")), patch("outage_explorer.infrastructure.parquet.storage.LocalParquetStore.__init__", side_effect=AssertionError("Storage constructed")):
                from outage_explorer.entrypoints.cli.connector_startup import main
                with patch.object(sys, "argv", ["build-connector-candidate", "--help"]):
                    try:
                        main()
                    except SystemExit as error:
                        assert error.code == 0
                app = create_app()
            assert app.test_client().get("/health").status_code == 200

            import os
            os.environ.update({
                "OUTAGE_AUTH_ENABLED": "true",
                "OUTAGE_ACCESS_DATABASE_DSN": "host=127.0.0.1 port=1 dbname=unused",
                "COGNITO_ISSUER": "https://cognito-idp.test/pool",
                "COGNITO_DOMAIN": "https://login.test",
                "COGNITO_APP_CLIENT_ID": "client",
                "COGNITO_OAUTH_SCOPES": "email",
                "OUTAGE_AUTH_PUBLIC_ORIGIN": "https://backend.test",
                "OUTAGE_AUTH_CALLBACK_URI": "https://backend.test/api/auth/callback",
                "OUTAGE_AUTH_DEVELOPMENT_HTTP": "false",
                "OUTAGE_AUTH_UI_ORIGIN": "https://ui.test",
            })
            with patch.object(SystemClock, "now", side_effect=AssertionError("Factory ran clock")), patch("httpx.Client.send", side_effect=AssertionError("Provider request")), patch("psycopg.connect", side_effect=AssertionError("DB connection")), patch("outage_explorer.bootstrap.run_migrations", side_effect=AssertionError("Migration ran")), patch("outage_explorer.bootstrap.execute_connector_to_s3", side_effect=AssertionError("Connector ran")):
                configured = create_app()
            assert configured.test_client().get("/health").status_code == 200
            assert configured.test_client().get("/api/auth/session").status_code == 401
            configured.extensions["outage_access_close"]()
    """)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
