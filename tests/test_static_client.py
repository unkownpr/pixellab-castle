from fastapi.testclient import TestClient

from castle_benchmark.api import create_app
from castle_benchmark.cli import build_parser


def test_built_frontend_is_served_without_shadowing_api(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Castle Console</h1>", encoding="utf-8")
    client = TestClient(create_app(static_dir=tmp_path))

    assert "Castle Console" in client.get("/").text
    assert client.get("/health").json() == {"status": "ok"}


def test_serve_command_has_safe_local_defaults():
    args = build_parser().parse_args(["serve"])

    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_report_command_accepts_completed_run_directory():
    args = build_parser().parse_args(["report", "runs/example"])

    assert args.run_dir.name == "example"
