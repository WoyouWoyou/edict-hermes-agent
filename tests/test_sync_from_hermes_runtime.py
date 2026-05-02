import json
import importlib.util
from pathlib import Path


def _load_sync_from_hermes_runtime():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "sync_from_hermes_runtime.py"
    spec = importlib.util.spec_from_file_location("sync_from_hermes_runtime", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_task_maps_hermes_session():
    sync = _load_sync_from_hermes_runtime()
    session = {
        "id": "sess-123456789",
        "source": "edict",
        "model": "openai/gpt-4o",
        "started_at": 1000.0,
        "input_tokens": 12,
        "output_tokens": 34,
        "messages": [
            {"role": "user", "content": "做个计划", "timestamp": 1000.0},
            {"role": "assistant", "content": "收到，我来规划。", "timestamp": 1001.0},
        ],
    }

    task = sync.build_task("zhongshu", session, now_ms=1001_500)

    assert task["id"] == "HM-zhongshu-sess-123"
    assert task["org"] == "中书省"
    assert task["state"] == "Doing"
    assert task["sourceMeta"]["runtime"] == "hermes"
    assert task["sourceMeta"]["totalTokens"] == 46
    assert task["activity"][0]["kind"] == "assistant"


def test_main_writes_status_and_preserves_jjc(tmp_path, monkeypatch):
    sync = _load_sync_from_hermes_runtime()
    data = tmp_path / "data"
    data.mkdir()
    (data / "tasks_source.json").write_text(
        json.dumps([{"id": "JJC-1", "title": "旨意", "state": "Doing"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "DATA", data)
    monkeypatch.setattr(sync, "SYNC_STATUS", data / "sync_status.json")
    monkeypatch.setattr(sync, "AGENT_IDS", ["taizi"])
    monkeypatch.setattr(sync, "export_profile_sessions", lambda agent: [{
        "id": "sess-abc",
        "source": "edict",
        "started_at": sync.time.time(),
        "messages": [{"role": "assistant", "content": "处理中", "timestamp": sync.time.time()}],
    }])

    sync.main()

    tasks = json.loads((data / "tasks_source.json").read_text(encoding="utf-8"))
    status = json.loads((data / "sync_status.json").read_text(encoding="utf-8"))
    assert any(t["id"] == "JJC-1" for t in tasks)
    assert any(str(t["id"]).startswith("HM-taizi") for t in tasks)
    assert status["source"] == "hermes_profile_sessions"
    assert status["ok"] is True
