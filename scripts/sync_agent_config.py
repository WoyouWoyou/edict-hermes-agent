#!/usr/bin/env python3
"""Sync Edict agent metadata from Hermes profiles into data/agent_config.json."""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re

from file_lock import atomic_json_write


log = logging.getLogger("sync_agent_config")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
AGENTS_DIR = BASE / "agents"
AGENTS_JSON = BASE / "agents.json"

AGENT_ORDER = [
    "taizi",
    "zhongshu",
    "menxia",
    "shangshu",
    "hubu",
    "libu",
    "bingbu",
    "xingbu",
    "gongbu",
    "libu_hr",
    "zaochao",
]

ID_LABEL = {
    "taizi": {"label": "太子", "role": "太子", "duty": "飞书消息分拣与回奏", "emoji": "🤴"},
    "zhongshu": {"label": "中书省", "role": "中书令", "duty": "起草任务令与优先级", "emoji": "📜"},
    "menxia": {"label": "门下省", "role": "侍中", "duty": "审议与退回机制", "emoji": "🔍"},
    "shangshu": {"label": "尚书省", "role": "尚书令", "duty": "派单与升级裁决", "emoji": "📮"},
    "libu": {"label": "礼部", "role": "礼部尚书", "duty": "文档/汇报/规范", "emoji": "📝"},
    "hubu": {"label": "户部", "role": "户部尚书", "duty": "资源/预算/成本", "emoji": "💰"},
    "bingbu": {"label": "兵部", "role": "兵部尚书", "duty": "工程实现与架构设计", "emoji": "⚔️"},
    "xingbu": {"label": "刑部", "role": "刑部尚书", "duty": "合规/审计/红线", "emoji": "⚖️"},
    "gongbu": {"label": "工部", "role": "工部尚书", "duty": "基础设施与部署运维", "emoji": "🔧"},
    "libu_hr": {"label": "吏部", "role": "吏部尚书", "duty": "人事/培训/Agent管理", "emoji": "👔"},
    "zaochao": {"label": "钦天监", "role": "朝报官", "duty": "每日新闻采集与简报", "emoji": "📰"},
}

KNOWN_MODELS = [
    {"id": "anthropic/claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "Anthropic"},
    {"id": "anthropic/claude-opus-4-5", "label": "Claude Opus 4.5", "provider": "Anthropic"},
    {"id": "anthropic/claude-haiku-3-5", "label": "Claude Haiku 3.5", "provider": "Anthropic"},
    {"id": "openai/gpt-4o", "label": "GPT-4o", "provider": "OpenAI"},
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o Mini", "provider": "OpenAI"},
    {"id": "openai-codex/gpt-5.3-codex", "label": "GPT-5.3 Codex", "provider": "OpenAI Codex"},
    {"id": "google/gemini-2.0-flash", "label": "Gemini 2.0 Flash", "provider": "Google"},
    {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro", "provider": "Google"},
    {"id": "copilot/claude-sonnet-4", "label": "Claude Sonnet 4", "provider": "Copilot"},
    {"id": "copilot/claude-opus-4.5", "label": "Claude Opus 4.5", "provider": "Copilot"},
    {"id": "github-copilot/claude-opus-4.6", "label": "Claude Opus 4.6", "provider": "GitHub Copilot"},
    {"id": "copilot/gpt-4o", "label": "GPT-4o", "provider": "Copilot"},
    {"id": "copilot/gemini-2.5-pro", "label": "Gemini 2.5 Pro", "provider": "Copilot"},
    {"id": "copilot/o3-mini", "label": "o3-mini", "provider": "Copilot"},
]


def hermes_root() -> pathlib.Path:
    raw = os.environ.get("HERMES_HOME", "").strip()
    path = pathlib.Path(raw).expanduser() if raw else pathlib.Path.home() / ".hermes"
    if path.parent.name == "profiles":
        return path.parent.parent
    return path


def profile_dir(agent_id: str) -> pathlib.Path:
    return hermes_root() / "profiles" / agent_id


def read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_scalar_config_value(config_path: pathlib.Path, key: str) -> str:
    if not config_path.exists():
        return ""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*[\"']?([^\"'#\n]+)")
    try:
        for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line)
            if match:
                return match.group(1).strip()
    except OSError:
        pass
    return ""


def get_model(agent_id: str, default_model: str) -> str:
    env_model = os.environ.get("HERMES_MODEL", "").strip()
    config_model = _read_scalar_config_value(profile_dir(agent_id) / "config.yaml", "model")
    return config_model or env_model or default_model


def get_skills(root: pathlib.Path):
    skills_dir = root / "skills"
    skills = []
    if not skills_dir.exists():
        return skills
    try:
        for md in sorted(skills_dir.rglob("SKILL.md")):
            rel_parts = md.relative_to(skills_dir).parts
            name = rel_parts[-2] if len(rel_parts) >= 2 else md.parent.name
            desc = ""
            try:
                for line in md.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("---"):
                        desc = line[:100]
                        break
            except OSError:
                desc = "(读取失败)"
            skills.append({"name": name, "path": str(md), "exists": True, "description": desc})
    except PermissionError as exc:
        log.warning("Skills 目录访问受限: %s", exc)
    return skills


def load_agent_entries():
    raw = read_json(AGENTS_JSON, [])
    entries = []
    seen = set()
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            agent_id = item.get("id")
            if agent_id in ID_LABEL and agent_id not in seen:
                entries.append(item)
                seen.add(agent_id)
    for agent_id in AGENT_ORDER:
        if agent_id not in seen:
            entries.append({"id": agent_id, "subagents": {"allowAgents": []}})
    entries.sort(key=lambda item: AGENT_ORDER.index(item["id"]))
    return entries


def _collect_hermes_models(default_model: str, entries: list[dict], overrides: dict[str, str] | None = None) -> list[dict]:
    known = {m["id"] for m in KNOWN_MODELS}
    models = list(KNOWN_MODELS)
    override_values = list((overrides or {}).values())
    for model_id in [default_model, *(get_model(e["id"], default_model) for e in entries), *override_values]:
        if model_id and model_id not in known:
            provider = model_id.split("/", 1)[0] if "/" in model_id else "Hermes"
            models.append({"id": model_id, "label": model_id, "provider": provider})
            known.add(model_id)
    return models


def _sync_script_symlink(src_file: pathlib.Path, dst_file: pathlib.Path) -> bool:
    """Create a symlink dst_file -> src_file. Kept for profile-local helpers."""
    src_resolved = src_file.resolve()
    try:
        dst_resolved = dst_file.resolve()
    except OSError:
        dst_resolved = None
    if dst_resolved == src_resolved:
        return False
    if dst_file.is_symlink() and dst_resolved == src_resolved:
        return False
    if dst_file.exists() or dst_file.is_symlink():
        dst_file.unlink()
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src_resolved, dst_file)
    return True


def sync_scripts_to_workspaces():
    """Sync project scripts into Hermes profile script folders as symlinks."""
    scripts_src = BASE / "scripts"
    if not scripts_src.is_dir():
        return
    synced = 0
    for agent_id in AGENT_ORDER:
        dst_dir = profile_dir(agent_id) / "scripts"
        for src_file in scripts_src.iterdir():
            if src_file.suffix not in (".py", ".sh") or src_file.stem.startswith("__"):
                continue
            try:
                if _sync_script_symlink(src_file, dst_dir / src_file.name):
                    synced += 1
            except Exception:
                continue
    if synced:
        log.info("%s script symlinks synced to Hermes profiles", synced)


def main():
    entries = load_agent_entries()
    default_model = os.environ.get("HERMES_MODEL", "anthropic/claude-sonnet-4-6")

    existing_cfg = read_json(DATA / "agent_config.json", {})
    model_overrides = existing_cfg.get("modelOverrides", {}) if isinstance(existing_cfg, dict) else {}
    if not isinstance(model_overrides, dict):
        model_overrides = {}
    model_overrides = {str(k): str(v).strip() for k, v in model_overrides.items() if str(v).strip()}
    known_models = _collect_hermes_models(default_model, entries, model_overrides)
    result = []
    for entry in entries:
        agent_id = entry["id"]
        meta = ID_LABEL[agent_id]
        pdir = profile_dir(agent_id)
        hermes_model = get_model(agent_id, default_model)
        model_override = model_overrides.get(agent_id, "")
        effective_model = model_override or hermes_model
        allow_agents = entry.get("allowAgents")
        if allow_agents is None:
            allow_agents = entry.get("subagents", {}).get("allowAgents", [])
        result.append({
            "id": agent_id,
            "label": meta["label"],
            "role": meta["role"],
            "duty": meta["duty"],
            "emoji": meta["emoji"],
            "model": effective_model,
            "hermesModel": hermes_model,
            "modelOverride": model_override,
            "modelSource": "manual" if model_override else "hermes",
            "defaultModel": default_model,
            "workspace": str(pdir),
            "profile": str(pdir),
            "profileExists": pdir.exists(),
            "skills": get_skills(pdir),
            "allowAgents": allow_agents or [],
            "runtime": "hermes",
        })

    payload = {
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runtime": "hermes",
        "hermesHome": str(hermes_root()),
        "defaultModel": default_model,
        "knownModels": known_models,
        "modelOverrides": model_overrides,
        "dispatchChannel": existing_cfg.get("dispatchChannel") or os.getenv("DEFAULT_DISPATCH_CHANNEL", ""),
        "agents": result,
    }
    DATA.mkdir(exist_ok=True)
    atomic_json_write(DATA / "agent_config.json", payload)
    log.info("%s Hermes agents synced", len(result))

    sync_scripts_to_workspaces()


if __name__ == "__main__":
    main()
