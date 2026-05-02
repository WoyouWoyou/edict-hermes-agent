import asyncio
import pathlib
import sys
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "edict" / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))


def test_call_hermes_builds_profile_command(monkeypatch, tmp_path):
    from app.workers import dispatch_worker
    monkeypatch.delenv("DISPATCH_HERMES_TOOLSETS", raising=False)
    monkeypatch.delenv("DISPATCH_HERMES_MAX_TURNS", raising=False)

    settings = SimpleNamespace(
        hermes_bin="hermes",
        hermes_home=str(tmp_path / ".hermes"),
        hermes_project_dir=str(tmp_path),
        hermes_source="edict",
        hermes_model="test-model",
        hermes_provider="test-provider",
        hermes_toolsets="terminal,skills",
        port=8000,
        dispatch_timeout_sec=12,
    )
    monkeypatch.setattr(dispatch_worker, "get_settings", lambda: settings)

    call = {}

    def fake_run(cmd, capture_output, text, timeout, env, cwd):
        call.update({
            "cmd": cmd,
            "capture_output": capture_output,
            "text": text,
            "timeout": timeout,
            "env": env,
            "cwd": cwd,
        })
        return SimpleNamespace(returncode=0, stdout="done", stderr="\nsession_id: abc")

    monkeypatch.setattr(dispatch_worker.subprocess, "run", fake_run)

    worker = object.__new__(dispatch_worker.DispatchWorker)
    result = asyncio.run(worker._call_hermes(
        agent="taizi",
        message="hello",
        task_id="T-1",
        trace_id="trace-1",
        payload={"title": "Title", "tags": ["a"]},
    ))

    assert result["returncode"] == 0
    assert result["stdout"] == "done"
    assert call["cmd"] == [
        "hermes",
        "--profile", "taizi",
        "chat",
        "-Q",
        "--accept-hooks",
        "--source", "edict",
        "--max-turns", "3",
        "--model", "test-model",
        "--provider", "test-provider",
        "--toolsets", "terminal,skills",
        "-q", "hello",
    ]
    assert call["timeout"] == 12
    assert call["cwd"] == str(tmp_path)
    assert call["env"]["HERMES_HOME"] == str(tmp_path / ".hermes")
    assert call["env"]["EDICT_TASK_ID"] == "T-1"
    assert "EDICT_CONTEXT_FILE" in call["env"]


def test_bootstrap_builds_layered_soul():
    import bootstrap_hermes_profiles as bootstrap

    soul = bootstrap.build_soul("zhongshu")

    assert "GLOBAL" in soul or "全局" in soul
    assert "中书" in soul
    assert "---" in soul
