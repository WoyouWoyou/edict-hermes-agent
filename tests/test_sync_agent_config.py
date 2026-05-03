import json
import importlib.util
from pathlib import Path


def _load_sync_agent_config():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "sync_agent_config.py"
    spec = importlib.util.spec_from_file_location("sync_agent_config", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_agent_config_uses_hermes_profiles(tmp_path, monkeypatch):
    sync_agent_config = _load_sync_agent_config()

    data_dir = tmp_path / "data"
    hermes_home = tmp_path / ".hermes"
    profile = hermes_home / "profiles" / "taizi"
    skill = profile / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Demo\nA migrated Hermes skill.\n", encoding="utf-8")
    (profile / "config.yaml").write_text("model: openai/gpt-4o\n", encoding="utf-8")

    agents_json = tmp_path / "agents.json"
    agents_json.write_text(json.dumps([
        {"id": "taizi", "allowAgents": ["zhongshu"]},
    ], ensure_ascii=False), encoding="utf-8")
    data_dir.mkdir()
    (data_dir / "hermes_model_overrides.json").write_text(json.dumps({
        "overrides": {"taizi": "openai/gpt-4o-mini"}
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(sync_agent_config, "DATA", data_dir)
    monkeypatch.setattr(sync_agent_config, "AGENTS_JSON", agents_json)
    monkeypatch.setattr(sync_agent_config, "AGENT_ORDER", ["taizi"])

    sync_agent_config.main()

    out = json.loads((data_dir / "agent_config.json").read_text(encoding="utf-8"))
    taizi = out["agents"][0]
    assert out["runtime"] == "hermes"
    assert taizi["id"] == "taizi"
    assert taizi["runtime"] == "hermes"
    assert taizi["profile"] == str(profile)
    assert taizi["profileExists"] is True
    assert taizi["hermesModel"] == "openai/gpt-4o"
    assert taizi["model"] == "openai/gpt-4o-mini"
    assert taizi["modelOverride"] == "openai/gpt-4o-mini"
    assert taizi["modelSource"] == "manual"
    assert taizi["allowAgents"] == ["zhongshu"]
    assert taizi["skills"][0]["name"] == "demo"
    assert out["modelOverrides"]["taizi"] == "openai/gpt-4o-mini"


def test_model_override_file_takes_precedence_when_empty(tmp_path, monkeypatch):
    sync_agent_config = _load_sync_agent_config()

    data_dir = tmp_path / "data"
    hermes_home = tmp_path / ".hermes"
    profile = hermes_home / "profiles" / "taizi"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("model: openai/gpt-4o\n", encoding="utf-8")

    agents_json = tmp_path / "agents.json"
    agents_json.write_text(json.dumps([
        {"id": "taizi", "allowAgents": []},
    ], ensure_ascii=False), encoding="utf-8")
    data_dir.mkdir()
    (data_dir / "agent_config.json").write_text(json.dumps({
        "modelOverrides": {"taizi": "openai/gpt-4o-mini"}
    }, ensure_ascii=False), encoding="utf-8")
    (data_dir / "hermes_model_overrides.json").write_text(json.dumps({
        "overrides": {}
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(sync_agent_config, "DATA", data_dir)
    monkeypatch.setattr(sync_agent_config, "AGENTS_JSON", agents_json)
    monkeypatch.setattr(sync_agent_config, "AGENT_ORDER", ["taizi"])

    sync_agent_config.main()

    out = json.loads((data_dir / "agent_config.json").read_text(encoding="utf-8"))
    taizi = out["agents"][0]
    assert taizi["model"] == "openai/gpt-4o"
    assert taizi["modelOverride"] == ""
    assert taizi["modelSource"] == "hermes"
    assert out["modelOverrides"] == {}
