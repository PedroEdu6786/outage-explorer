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
            with patch.object(Flask, "__init__", side_effect=AssertionError("Import created an app")):
                import outage_explorer
                for module in pkgutil.walk_packages(outage_explorer.__path__, "outage_explorer."):
                    importlib.import_module(module.name)

            from outage_explorer.infrastructure.clock import SystemClock
            from outage_explorer.entrypoints.http.startup import create_app
            with patch.object(SystemClock, "now", side_effect=AssertionError("Factory ran probe")):
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
