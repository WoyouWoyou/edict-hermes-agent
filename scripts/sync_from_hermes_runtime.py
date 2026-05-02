#!/usr/bin/env python3
"""Sync Hermes profile sessions into Edict's live task feed."""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import subprocess
import time
import traceback

from file_lock import atomic_json_write


log = logging.getLogger("sync_hermes_runtime")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
SYNC_STATUS = DATA / "sync_status.json"
DATA.mkdir(exist_ok=True)

AGENT_IDS = [
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


def write_status(**kwargs):
    atomic_json_write(SYNC_STATUS, kwargs)


def hermes_root() -> pathlib.Path:
    raw = os.environ.get("HERMES_HOME", "").strip()
    path = pathlib.Path(raw).expanduser() if raw else pathlib.Path.home() / ".hermes"
    if path.parent.name == "profiles":
        return path.parent.parent
    return path


def detect_official(agent_id):
    mapping = {
        "taizi": ("储君", "太子"),
        "zhongshu": ("中书令", "中书省"),
        "menxia": ("侍中", "门下省"),
        "shangshu": ("尚书令", "尚书省"),
        "hubu": ("户部尚书", "户部"),
        "libu": ("礼部尚书", "礼部"),
        "bingbu": ("兵部尚书", "兵部"),
        "xingbu": ("刑部尚书", "刑部"),
        "gongbu": ("工部尚书", "工部"),
        "libu_hr": ("吏部尚书", "吏部"),
        "zaochao": ("钦天监", "钦天监"),
    }
    return mapping.get(agent_id, ("尚书令", "尚书省"))


def to_epoch_ms(value) -> int:
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value * 1000) if value < 10_000_000_000 else int(value)
    try:
        return int(datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


def ms_to_str(ts_ms: int) -> str:
    if not ts_ms:
        return "-"
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def state_from_session(age_ms: int, ended: bool) -> str:
    if ended:
        return "Next"
    if age_ms <= 2 * 60 * 1000:
        return "Doing"
    if age_ms <= 60 * 60 * 1000:
        return "Review"
    return "Next"


def content_to_text(content) -> str:
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return content_to_text(parsed)
        except Exception:
            return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return "" if content is None else str(content)


def load_activity(session: dict, limit=12):
    rows = []
    for msg in reversed(session.get("messages") or []):
        role = msg.get("role", "")
        text = content_to_text(msg.get("content", "")).replace("[[reply_to_current]]", "").strip()
        if not text:
            continue
        ts = msg.get("timestamp") or ""
        if role == "assistant":
            summary = text.splitlines()[0][:200]
            rows.append({"at": ts, "kind": "assistant", "text": summary})
        elif role == "tool":
            rows.append({"at": ts, "kind": "tool", "text": f"Tool finished: {text[:80]}"})
        elif role == "user":
            rows.append({"at": ts, "kind": "user", "text": f"User: {text[:100]}"})
        if len(rows) >= limit:
            break
    return rows


def build_task(agent_id: str, session: dict, now_ms: int) -> dict:
    session_id = session.get("id", "")
    latest_ts = max(
        [to_epoch_ms(m.get("timestamp")) for m in (session.get("messages") or [])] +
        [to_epoch_ms(session.get("ended_at")), to_epoch_ms(session.get("started_at"))]
    )
    age_ms = max(0, now_ms - latest_ts) if latest_ts else 99 * 24 * 3600 * 1000
    ended = bool(session.get("ended_at"))
    state = state_from_session(age_ms, ended)
    official, org = detect_official(agent_id)
    acts = load_activity(session, limit=10)
    latest = "等待指令"
    if acts:
        latest = acts[0]["text"][:100]
        if acts[0]["kind"] == "assistant":
            latest = f"思考中: {latest}"

    title = session.get("title") or session.get("preview") or f"{org}会话"
    return {
        "id": f"HM-{agent_id}-{str(session_id)[:8]}",
        "title": str(title)[:80],
        "official": official,
        "org": org,
        "state": state,
        "now": latest,
        "eta": ms_to_str(latest_ts),
        "block": "无",
        "output": "",
        "flow": {
            "draft": f"profile={agent_id}",
            "review": f"updatedAt={ms_to_str(latest_ts)}",
            "dispatch": f"sessionId={session_id}",
        },
        "ac": "来自 Hermes profile sessions 的实时映射",
        "activity": acts,
        "sourceMeta": {
            "runtime": "hermes",
            "agentId": agent_id,
            "sessionId": session_id,
            "source": session.get("source"),
            "updatedAt": latest_ts,
            "ageMs": age_ms,
            "ended": ended,
            "inputTokens": session.get("input_tokens"),
            "outputTokens": session.get("output_tokens"),
            "totalTokens": (session.get("input_tokens") or 0) + (session.get("output_tokens") or 0),
            "model": session.get("model"),
        },
    }


def export_profile_sessions(agent_id: str) -> list[dict]:
    hermes_bin = os.environ.get("HERMES_BIN", "hermes")
    source = os.environ.get("HERMES_SOURCE", "edict")
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_root())
    cmd = [hermes_bin, "--profile", agent_id, "sessions", "export", "-", "--source", source]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        log.debug("Hermes session export failed for %s: %s", agent_id, result.stderr.strip())
        return []
    sessions = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                sessions.append(item)
        except json.JSONDecodeError:
            continue
    return sessions


def read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def merge_existing_jjc(tasks: list[dict]) -> list[dict]:
    existing = read_json(DATA / "tasks_source.json", [])
    if not isinstance(existing, list):
        return tasks
    jjc_existing = [t for t in existing if str(t.get("id", "")).startswith("JJC")]
    tasks = [t for t in tasks if not str(t.get("id", "")).startswith("JJC")]
    return jjc_existing + tasks


def main():
    start = time.time()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_ms = int(time.time() * 1000)
    try:
        tasks = []
        scanned = 0
        for agent_id in AGENT_IDS:
            sessions = export_profile_sessions(agent_id)
            scanned += len(sessions)
            for session in sessions:
                tasks.append(build_task(agent_id, session, now_ms))

        for extra_file in ("mission_control_tasks.json", "manual_parallel_tasks.json"):
            extra = read_json(DATA / extra_file, [])
            if isinstance(extra, list):
                tasks.extend(extra)

        one_day_ago = now_ms - 24 * 3600 * 1000
        filtered = []
        for task in tasks:
            if str(task.get("id", "")).startswith("JJC"):
                filtered.append(task)
                continue
            updated = task.get("sourceMeta", {}).get("updatedAt", 0)
            if updated < one_day_ago:
                continue
            if task.get("state") not in ("Doing", "Review", "Blocked"):
                continue
            filtered.append(task)

        filtered.sort(key=lambda x: x.get("sourceMeta", {}).get("updatedAt", 0), reverse=True)
        tasks = merge_existing_jjc(filtered)
        seen = set()
        deduped = []
        for task in tasks:
            task_id = task.get("id")
            if task_id in seen:
                continue
            seen.add(task_id)
            deduped.append(task)

        atomic_json_write(DATA / "tasks_source.json", deduped)
        duration_ms = int((time.time() - start) * 1000)
        write_status(
            ok=True,
            lastSyncAt=now,
            durationMs=duration_ms,
            source="hermes_profile_sessions",
            recordCount=len(deduped),
            scannedSessionFiles=scanned,
            missingFields={},
            error=None,
        )
        log.info("synced %s tasks from Hermes runtime in %sms", len(deduped), duration_ms)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        write_status(
            ok=False,
            lastSyncAt=now,
            durationMs=duration_ms,
            source="hermes_profile_sessions",
            recordCount=0,
            missingFields={},
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(limit=3),
        )
        raise


if __name__ == "__main__":
    main()
