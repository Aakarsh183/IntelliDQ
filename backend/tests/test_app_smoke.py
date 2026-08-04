"""Import-and-wiring smoke tests for the served FastAPI app.

The most valuable tests in this repo: importing main_app pulls in grok_client,
column_resolver and rag, so these catch every missing dependency and every
import-time crash in one shot.

Deliberately no SparkSession is created here. get_spark() is lazy, so importing
the module is JVM-free - which is why main_app.py overwriting JAVA_HOME with a
Windows path at module scope does not break this suite. That path is still a
portability bug for anything that actually runs Spark on Linux.
"""

import main_app

# Routes the frontend (dq-app/src/api.js) depends on.
EXPECTED_ROUTES = (
    "/upload",
    "/get_mappings",
    "/generate_code",
    "/regenerate_code",
    "/suggest_columns",
    "/execute_code",
    "/add_rule",
    "/rag_query",
)


def test_app_imports_and_exposes_expected_routes():
    paths = {route.path for route in main_app.app.routes}
    missing = [path for path in EXPECTED_ROUTES if path not in paths]
    assert not missing, f"routes missing from main_app.app: {missing}"


def test_upload_rejects_a_request_with_no_files():
    from fastapi.testclient import TestClient

    client = TestClient(main_app.app)
    # dataset and rules are required UploadFiles, so FastAPI validation rejects
    # this before any handler code (and therefore any Spark call) is reached.
    assert client.post("/upload").status_code == 422
