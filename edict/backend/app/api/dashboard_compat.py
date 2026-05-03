"""Compatibility endpoints for the React dashboard.

The current backend exposes resource-oriented routes such as
``/api/tasks/live-status``.  The dashboard was originally written against the
single-file dashboard server and still polls root-level ``/api/...`` paths.
These adapters keep the UI usable while the frontend is migrated route by
route.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models.task import ORG_AGENT_MAP, STATE_AGENT_MAP, Task, TaskState, TERMINAL_STATES
from ..services.event_bus import get_event_bus
from ..services.task_service import TaskService

router = APIRouter()

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_SKILL_BYTES = 10 * 1024 * 1024
_OFFICIALS_SYNC_LAST_ATTEMPT = 0.0


AGENT_META = {
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
    {"id": "openai/gpt-4o", "label": "GPT-4o", "provider": "OpenAI"},
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o Mini", "provider": "OpenAI"},
    {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro", "provider": "Google"},
]

COURT_DETAILS = {
    "taizi": ("年轻有为、锐意进取，偶尔冲动但善于学习。", "简洁有力，常以“本宫以为”开头。"),
    "zhongshu": ("老成持重，擅长规划，总能提出系统性方案。", "喜欢列点论述，常说“臣以为需从三方面考量”。"),
    "menxia": ("严谨挑剔，眼光犀利，善于找漏洞。", "常从风险、可行性与完整性追问。"),
    "shangshu": ("务实干练，关注派单、节奏和资源分配。", "直来直去，常说“臣来安排”。"),
    "libu": ("注重规范与表达，擅长文档和对外沟通。", "措辞端正，偏重口径、模板与可读性。"),
    "hubu": ("精打细算，对预算和资源敏感。", "言必及成本、收益和复用。"),
    "bingbu": ("雷厉风行，危机意识强。", "强调执行速度、稳定性和应急预案。"),
    "xingbu": ("严明公正，重视质量、规则和底线。", "逻辑严密，常提醒测试、权限和审计。"),
    "gongbu": ("动手能力强，喜欢谈实现细节。", "从接口、数据结构、部署和脚本落地。"),
    "libu_hr": ("知人善任，擅长团队建设和能力匹配。", "关注角色分工、培训与协作规范。"),
}

COURT_RESPONSE_TEMPLATES = {
    "taizi": [
        "本宫以为先拆小步：确认目标、列出阻塞，再交由相应衙门推进。",
        "此事可先做轻量试运行，跑通后再扩到全局。",
    ],
    "zhongshu": [
        "臣以为需从目标、路径、验收三方面定纲，先成章法再谈执行。",
        "建议先拟一份简明方案：谁负责、何时交付、以何为准。",
    ],
    "menxia": [
        "陛下容禀，此处需审三点：边界是否清楚、失败是否可退、责任是否可追。",
        "若无验收口径，后续容易各执一词，臣请先补准入与回滚标准。",
    ],
    "shangshu": [
        "臣来安排：能立即办的先派，需审议的标明依赖，统一回奏进度。",
        "此事宜分两路，一路落地，一路巡查风险，不可互相等待。",
    ],
    "libu": [
        "臣斗胆建议同步整理说明文档，免得功能虽成，使用者仍不知其门。",
        "对外口径宜清楚：能做什么、不能做什么、如何启动、如何回退。",
    ],
    "hubu": [
        "这个预算嘛，先复用现有 profile 与脚本，少起常驻服务，最合算。",
        "若要长期运行，应把耗时任务和高频轮询分开，避免白白耗费资源。",
    ],
    "bingbu": [
        "末将建议立即补监控与日志入口，出了问题能一眼定位。",
        "兵贵神速，但部署前需留回滚命令，避免一处失守全盘受扰。",
    ],
    "xingbu": [
        "依律当如此：写入、删除、远程下载都要校验名称与来源，不能放任路径穿越。",
        "臣请加一层审计记录，至少保留来源、校验和与更新时间。",
    ],
    "gongbu": [
        "从技术角度看，可以把旧 dashboard API 迁到 Hermes profile 目录，前端无需大改。",
        "建议后端只做轻量同步，真正推理仍交给 Hermes CLI 或 dispatcher。",
    ],
    "libu_hr": [
        "此事需考虑各部人手：技能安装归吏部维护，执行归各 profile 自用。",
        "建议给每个新 skill 留说明、触发条件和维护来源，便于后续交接。",
    ],
}

FATE_EVENTS = [
    "八百里加急：边疆战报传来，所有人必须讨论应急方案",
    "钦天监急报：天象异常，建议暂缓此事并补充验证",
    "新科状元觐见，带来了一个意想不到的新视角",
    "匿名奏折揭露了计划中一个被忽视的漏洞",
    "户部清点发现资源比预期充足，可以加大投入",
    "民间舆论突变，使用者诉求发生明显变化",
    "邻国使节来访，带来了合作机遇也带来了竞争压力",
    "太后懿旨：要求优先考虑稳定性与易用性",
]


class CreateTaskBody(BaseModel):
    title: str
    org: str = "中书省"
    targetDept: str | None = None
    priority: str = "中"
    templateId: str = ""
    params: dict[str, str] = {}


class TaskActionBody(BaseModel):
    taskId: str
    action: str
    reason: str = ""


class ReviewActionBody(BaseModel):
    taskId: str
    action: str
    comment: str = ""


class AdvanceStateBody(BaseModel):
    taskId: str
    comment: str = ""


class ArchiveTaskBody(BaseModel):
    taskId: str | None = None
    archived: bool = True
    archiveAllDone: bool = False


class AgentWakeBody(BaseModel):
    agentId: str
    message: str = ""


class ModelBody(BaseModel):
    agentId: str
    model: str


class DispatchChannelBody(BaseModel):
    channel: str


class ProfileTestBody(BaseModel):
    agentId: str
    prompt: str = "只回复：Hermes OK"


class AddSkillBody(BaseModel):
    agentId: str
    skillName: str
    description: str = ""
    trigger: str = ""


class AddRemoteSkillBody(BaseModel):
    agentId: str
    skillName: str
    sourceUrl: str
    description: str = ""


class RemoteSkillBody(BaseModel):
    agentId: str
    skillName: str


class CourtStartBody(BaseModel):
    topic: str
    officials: list[str]
    taskId: str = ""


class CourtAdvanceBody(BaseModel):
    sessionId: str
    userMessage: str | None = None
    decree: str | None = None


class CourtSessionBody(BaseModel):
    sessionId: str


def _project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [Path.cwd(), *here.parents]
    for base in candidates:
        if (base / "data").exists() or (base / "agents").exists():
            return base
    return here.parents[2]


def _data_dir() -> Path:
    path = _project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(name: str, default: Any) -> Any:
    try:
        return json.loads((_data_dir() / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(name: str, payload: Any) -> None:
    (_data_dir() / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _log_dt(item: dict[str, Any]) -> datetime | None:
    return _parse_dt(item.get("at") or item.get("ts") or item.get("timestamp"))


def _agent_id_from_value(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in AGENT_META:
        return text
    for agent_id, meta in AGENT_META.items():
        if text in {meta["label"], meta["role"]}:
            return agent_id
    aliases = {
        "太子": "taizi",
        "中书省": "zhongshu",
        "中书令": "zhongshu",
        "门下省": "menxia",
        "侍中": "menxia",
        "尚书省": "shangshu",
        "尚书令": "shangshu",
        "礼部": "libu",
        "礼部尚书": "libu",
        "户部": "hubu",
        "户部尚书": "hubu",
        "兵部": "bingbu",
        "兵部尚书": "bingbu",
        "刑部": "xingbu",
        "刑部尚书": "xingbu",
        "工部": "gongbu",
        "工部尚书": "gongbu",
        "吏部": "libu_hr",
        "吏部尚书": "libu_hr",
        "钦天监": "zaochao",
        "朝报官": "zaochao",
    }
    return aliases.get(text)


def _task_state(task: Task) -> TaskState | None:
    if isinstance(task.state, TaskState):
        return task.state
    try:
        return TaskState(str(task.state))
    except ValueError:
        return None


def _active_agent_for_task(task: Task) -> str | None:
    state = _task_state(task)
    if state in {TaskState.Doing, TaskState.Next}:
        return ORG_AGENT_MAP.get(task.assignee_org or task.target_dept or "")
    if state == TaskState.Blocked:
        return _last_agent_for_task(task)
    if state in TERMINAL_STATES:
        return None
    return STATE_AGENT_MAP.get(state) if state else None


def _last_agent_for_task(task: Task) -> str | None:
    latest: tuple[datetime, str] | None = None
    for item in [*(task.flow_log or []), *(task.progress_log or [])]:
        if not isinstance(item, dict):
            continue
        agent_id = _agent_id_from_value(item.get("agent") or item.get("from") or item.get("to"))
        at = _log_dt(item)
        if agent_id and at and (latest is None or at > latest[0]):
            latest = (at, agent_id)
    return latest[1] if latest else None


def _task_ref(task: Task) -> dict[str, str]:
    meta = task.meta or {}
    state = _task_state(task)
    return {
        "id": str(meta.get("legacy_id") or task.task_id),
        "title": task.title,
        "state": state.value if state else str(task.state or ""),
    }


def _latest_progress_text(task: Task, preferred_agents: tuple[str, ...] = ()) -> str:
    entries = [item for item in (task.progress_log or []) if isinstance(item, dict)]
    if preferred_agents:
        preferred = [item for item in entries if item.get("agent") in preferred_agents]
        if preferred:
            entries = preferred
    if not entries:
        return ""
    entries.sort(key=lambda item: _log_dt(item) or datetime.min.replace(tzinfo=timezone.utc))
    latest = entries[-1]
    return str(latest.get("content") or latest.get("text") or "").strip()


def _estimate_tokens(text: str) -> int:
    compact = str(text or "").strip()
    if not compact:
        return 0
    return max(1, len(compact) // 2)


def _rank_for_agent(agent_id: str) -> str:
    if agent_id in {"zhongshu", "menxia", "shangshu"}:
        return "正一品"
    if agent_id in {"taizi", "zaochao"}:
        return "正二品"
    return "正三品"


def _infer_execution_org(title: str, params: dict[str, str], requested: str | None) -> str | None:
    if requested in ORG_AGENT_MAP:
        return requested
    text = f"{title} {' '.join(str(v) for v in (params or {}).values())}"
    if any(word in text for word in ("自媒体", "文案", "漫画", "内容", "表达", "传播", "汇报", "新闻")):
        return "礼部"
    if any(word in text for word in ("部署", "Docker", "docker", "服务", "端口", "运维", "脚本")):
        return "工部"
    if any(word in text for word in ("代码", "开发", "实现", "架构", "接口", "前端", "后端")):
        return "兵部"
    if any(word in text for word in ("成本", "预算", "费用", "token", "Token", "资源")):
        return "户部"
    if any(word in text for word in ("合规", "审计", "风险", "权限", "安全")):
        return "刑部"
    return None


def _build_officials_from_tasks(tasks: list[Task]) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc)
    officials: dict[str, dict[str, Any]] = {
        agent_id: {
            "id": agent_id,
            **meta,
            "rank": _rank_for_agent(agent_id),
            "model": "",
            "model_short": "",
            "tokens_in": 0,
            "tokens_out": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost_cny": 0,
            "cost_usd": 0,
            "sessions": 0,
            "messages": 0,
            "tasks_done": 0,
            "tasks_active": 0,
            "flow_participations": 0,
            "merit_score": 0,
            "merit_rank": 0,
            "last_active": "",
            "heartbeat": {"status": "idle", "label": "Hermes profile 待命"},
            "participated_edicts": [],
            "_last_active_dt": None,
            "_task_ids": set(),
            "_done_ids": set(),
            "_edict_ids": set(),
        }
        for agent_id, meta in AGENT_META.items()
    }

    for task in tasks:
        task_ref = _task_ref(task)
        active_agent = _active_agent_for_task(task)
        state = _task_state(task)
        if active_agent in officials and state not in TERMINAL_STATES:
            officials[active_agent]["tasks_active"] += 1
            officials[active_agent]["_task_ids"].add(str(task.task_id))
            officials[active_agent]["_edict_ids"].add(task_ref["id"])
            officials[active_agent]["participated_edicts"].append(task_ref)

        participants: set[str] = set()
        for item in task.flow_log or []:
            if not isinstance(item, dict):
                continue
            agent_id = _agent_id_from_value(item.get("agent") or item.get("from") or item.get("to"))
            if agent_id not in officials:
                continue
            participants.add(agent_id)
            stat = officials[agent_id]
            stat["flow_participations"] += 1
            stat["_task_ids"].add(str(task.task_id))
            at = _log_dt(item)
            if at and (stat["_last_active_dt"] is None or at > stat["_last_active_dt"]):
                stat["_last_active_dt"] = at

        for item in task.progress_log or []:
            if not isinstance(item, dict):
                continue
            agent_id = _agent_id_from_value(item.get("agent"))
            if agent_id not in officials:
                continue
            participants.add(agent_id)
            stat = officials[agent_id]
            text = str(item.get("content") or item.get("text") or "")
            stat["messages"] += 1
            stat["tokens_in"] += _estimate_tokens(task.title) + _estimate_tokens(task.description)
            stat["tokens_out"] += _estimate_tokens(text)
            stat["_task_ids"].add(str(task.task_id))
            at = _log_dt(item)
            if at and (stat["_last_active_dt"] is None or at > stat["_last_active_dt"]):
                stat["_last_active_dt"] = at

        if state in TERMINAL_STATES:
            for agent_id in participants:
                officials[agent_id]["_done_ids"].add(str(task.task_id))

        for agent_id in participants:
            stat = officials[agent_id]
            if task_ref["id"] not in stat["_edict_ids"]:
                stat["_edict_ids"].add(task_ref["id"])
                stat["participated_edicts"].append(task_ref)

    rows = list(officials.values())
    for stat in rows:
        last_active = stat.pop("_last_active_dt")
        task_ids = stat.pop("_task_ids")
        done_ids = stat.pop("_done_ids")
        stat.pop("_edict_ids")
        stat["sessions"] = len(task_ids)
        stat["tasks_done"] = len(done_ids)
        stat["merit_score"] = (
            stat["tasks_done"] * 10
            + stat["tasks_active"] * 3
            + stat["flow_participations"] * 2
            + stat["messages"]
        )
        if last_active:
            stat["last_active"] = last_active.isoformat()
        if stat["tasks_active"] > 0:
            state_label = "阻塞待处理" if any(t.get("state") == TaskState.Blocked.value for t in stat["participated_edicts"]) else "处理中"
            stat["heartbeat"] = {"status": "active", "label": state_label}
        elif last_active and (checked_at - last_active).total_seconds() <= 15 * 60:
            stat["heartbeat"] = {"status": "idle", "label": "刚刚处理过"}

    rows.sort(key=lambda row: (-row["merit_score"], row["id"]))
    for idx, stat in enumerate(rows, start=1):
        stat["merit_rank"] = idx
    top = rows[0]["label"] if rows and rows[0]["merit_score"] > 0 else ""
    rows.sort(key=lambda row: list(AGENT_META).index(row["id"]))
    return {
        "officials": rows,
        "totals": {
            "tasks_done": sum(1 for task in tasks if _task_state(task) in TERMINAL_STATES),
            "cost_cny": round(sum(row["cost_cny"] for row in rows), 4),
        },
        "top_official": top,
    }


def _validate_safe_name(value: str, label: str) -> str:
    cleaned = value.strip()
    if not SAFE_NAME_RE.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail=f"{label} must match [A-Za-z0-9_-] and be 1-64 chars")
    return cleaned


def _validate_agent_id(agent_id: str) -> str:
    cleaned = _validate_safe_name(agent_id, "agentId")
    cfg = _read_json("agent_config.json", {})
    known = {agent["id"] for agent in cfg.get("agents", []) if isinstance(agent, dict) and agent.get("id")}
    if not known:
        known = set(AGENT_META)
    if cleaned not in known:
        raise HTTPException(status_code=404, detail=f"Unknown Hermes agent/profile: {cleaned}")
    return cleaned


def _hermes_home() -> Path:
    cfg = _read_json("agent_config.json", {})
    configured = cfg.get("hermesHome") if isinstance(cfg, dict) else None
    return Path(os.environ.get("HERMES_HOME") or configured or (Path.home() / ".hermes")).expanduser()


def _profile_dir(agent_id: str) -> Path:
    cfg = _read_json("agent_config.json", {})
    if isinstance(cfg, dict):
        for agent in cfg.get("agents", []):
            if isinstance(agent, dict) and agent.get("id") == agent_id and agent.get("profile"):
                return Path(agent["profile"])
    return _hermes_home() / "profiles" / agent_id


def _profile_skill_dir(agent_id: str, skill_name: str) -> Path:
    return _profile_dir(agent_id) / "skills" / skill_name


def _read_profile_scalar(config_path: Path, key: str) -> str:
    if not config_path.exists():
        return ""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*[\"']?([^\"'#\n]+)")
    try:
        for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line)
            if match:
                return match.group(1).strip()
    except OSError:
        return ""
    return ""


def _profile_status(agent_id: str, agent_row: dict[str, Any] | None = None) -> dict[str, Any]:
    pdir = _profile_dir(agent_id)
    config_path = pdir / "config.yaml"
    env_path = pdir / ".env"
    skills_dir = pdir / "skills"
    meta = AGENT_META.get(agent_id, {})
    model = _read_profile_scalar(config_path, "model") or (agent_row or {}).get("model") or ""
    provider = _read_profile_scalar(config_path, "provider")
    skills = (agent_row or {}).get("skills") or []
    if not isinstance(skills, list):
        skills = []
    if not skills and skills_dir.exists():
        skills = [
            {"name": path.parent.name, "path": str(path), "exists": True, "description": ""}
            for path in sorted(skills_dir.glob("*/SKILL.md"))
        ]
    return {
        "id": agent_id,
        "label": (agent_row or {}).get("label") or meta.get("label") or agent_id,
        "emoji": (agent_row or {}).get("emoji") or meta.get("emoji") or "🏛️",
        "role": (agent_row or {}).get("role") or meta.get("role") or "",
        "duty": (agent_row or {}).get("duty") or meta.get("duty") or "",
        "profile": str(pdir),
        "profileExists": pdir.exists(),
        "configExists": config_path.exists(),
        "envExists": env_path.exists(),
        "skillsDirExists": skills_dir.exists(),
        "skillsCount": len(skills),
        "skills": skills,
        "model": model,
        "provider": provider,
        "runtime": "hermes",
    }


def _find_profile_config_source(target_agent_id: str | None = None) -> Path | None:
    root = _hermes_home() / "profiles"
    preferred = [
        os.environ.get("COURT_HERMES_CONFIG_PROFILE", ""),
        os.environ.get("HERMES_CONFIG_SOURCE_PROFILE", ""),
        "taizi",
    ]
    for agent_id in preferred:
        if not agent_id or agent_id == target_agent_id:
            continue
        candidate = root / agent_id
        if (candidate / "config.yaml").exists() or (candidate / ".env").exists():
            return candidate
    if root.exists():
        for candidate in sorted(root.iterdir()):
            if candidate.name == target_agent_id or not candidate.is_dir():
                continue
            if (candidate / "config.yaml").exists() or (candidate / ".env").exists():
                return candidate
    return None


def _ensure_profile_runtime_config(agent_id: str) -> None:
    target = _profile_dir(agent_id)
    target.mkdir(parents=True, exist_ok=True)
    if (target / "config.yaml").exists() and (target / ".env").exists():
        return
    source = _find_profile_config_source(agent_id)
    if not source:
        return
    for name in ("config.yaml", ".env"):
        src = source / name
        dst = target / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def _checksum(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sync_agent_config() -> None:
    script = _project_root() / "scripts" / "sync_agent_config.py"
    if script.exists():
        try:
            subprocess.run(
                [sys.executable, str(script)],
                cwd=str(_project_root()),
                env={**os.environ, "HERMES_HOME": str(_hermes_home())},
                check=False,
                timeout=20,
                capture_output=True,
                text=True,
            )
            return
        except Exception:
            pass

    cfg = _read_json("agent_config.json", {})
    if not isinstance(cfg, dict) or not isinstance(cfg.get("agents"), list):
        return
    for agent in cfg["agents"]:
        if not isinstance(agent, dict) or not agent.get("id"):
            continue
        skills_dir = _profile_dir(agent["id"]) / "skills"
        skills = []
        if skills_dir.exists():
            for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
                skills.append(skill_file.parent.name)
        agent["skills"] = skills
    cfg["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg["runtime"] = "hermes"
    cfg["hermesHome"] = str(_hermes_home())
    _write_json("agent_config.json", cfg)


def _maybe_sync_officials_stats() -> None:
    global _OFFICIALS_SYNC_LAST_ATTEMPT
    script = _project_root() / "scripts" / "sync_officials_stats.py"
    if not script.exists():
        return
    cached = _read_json("officials_stats.json", {})
    generated = _parse_dt(cached.get("generatedAt")) if isinstance(cached, dict) else None
    if generated and (datetime.now(timezone.utc) - generated).total_seconds() < 30:
        return
    if time.time() - _OFFICIALS_SYNC_LAST_ATTEMPT < 30:
        return
    _OFFICIALS_SYNC_LAST_ATTEMPT = time.time()
    try:
        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(_project_root()),
            env={**os.environ, "HERMES_HOME": str(_hermes_home())},
            check=False,
            timeout=12,
            capture_output=True,
            text=True,
        )
    except Exception:
        return


def _merge_runtime_official_stats(stats: dict[str, Any]) -> dict[str, Any]:
    _maybe_sync_officials_stats()
    runtime = _read_json("officials_stats.json", {})
    runtime_rows = {
        row.get("id"): row
        for row in runtime.get("officials", [])
        if isinstance(row, dict) and row.get("id")
    } if isinstance(runtime, dict) else {}
    if not runtime_rows:
        stats["statsSource"] = "tasks"
        return stats

    token_fields = (
        "model",
        "model_short",
        "tokens_in",
        "tokens_out",
        "cache_read",
        "cache_write",
        "cost_cny",
        "cost_usd",
        "sessions",
        "messages",
        "last_active",
    )
    for row in stats.get("officials", []):
        runtime_row = runtime_rows.get(row.get("id")) or {}
        for field in token_fields:
            value = runtime_row.get(field)
            if value not in (None, ""):
                row[field] = value
        row["merit_score"] = (
            int(row.get("tasks_done") or 0) * 10
            + int(row.get("tasks_active") or 0) * 3
            + int(row.get("flow_participations") or 0) * 2
            + min(int(row.get("sessions") or 0), 20)
            + int(row.get("messages") or 0)
        )

    ranked = sorted(stats.get("officials", []), key=lambda row: (-int(row.get("merit_score") or 0), row.get("id") or ""))
    for idx, row in enumerate(ranked, start=1):
        row["merit_rank"] = idx
    top = ranked[0]["label"] if ranked and ranked[0].get("merit_score", 0) > 0 else ""
    stats["top_official"] = top
    stats["totals"] = {
        **(stats.get("totals") or {}),
        "tokens_total": sum((row.get("tokens_in") or 0) + (row.get("tokens_out") or 0) for row in stats.get("officials", [])),
        "cache_total": sum((row.get("cache_read") or 0) + (row.get("cache_write") or 0) for row in stats.get("officials", [])),
        "cost_cny": round(sum(row.get("cost_cny") or 0 for row in stats.get("officials", [])), 2),
        "cost_usd": round(sum(row.get("cost_usd") or 0 for row in stats.get("officials", [])), 4),
    }
    stats["statsSource"] = "hermes_sessions+tasks"
    stats["runtimeGeneratedAt"] = runtime.get("generatedAt", "")
    return stats


def _read_source_text(source_url: str) -> tuple[str, str]:
    source_url = source_url.strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="sourceUrl required")

    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https"}:
        req = Request(source_url, headers={"User-Agent": "Edict-Hermes-SkillManager/1.0"})
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read(MAX_SKILL_BYTES + 1)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"download failed: {exc}") from exc
        if len(data) > MAX_SKILL_BYTES:
            raise HTTPException(status_code=400, detail="remote skill is larger than 10MB")
        return data.decode("utf-8"), source_url

    if parsed.scheme == "file":
        path = Path(parsed.path)
    else:
        path = Path(source_url)
        if not path.is_absolute():
            path = _project_root() / path
    try:
        resolved = path.expanduser().resolve()
        content = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"read source failed: {exc}") from exc
    if len(content.encode("utf-8")) > MAX_SKILL_BYTES:
        raise HTTPException(status_code=400, detail="skill file is larger than 10MB")
    return content, str(resolved)


def _ensure_skill_markdown(content: str) -> None:
    if len(content.strip()) < 20:
        raise HTTPException(status_code=400, detail="skill content is too short")
    if "SKILL" not in content[:2000].upper() and "#" not in content[:2000]:
        raise HTTPException(status_code=400, detail="source does not look like a Hermes SKILL.md")


def _install_skill(
    agent_id: str,
    skill_name: str,
    content: str,
    source_url: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    agent_id = _validate_agent_id(agent_id)
    skill_name = _validate_safe_name(skill_name, "skillName")
    _ensure_skill_markdown(content)

    target_dir = _profile_skill_dir(agent_id, skill_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    target.write_text(content.rstrip() + "\n", encoding="utf-8")

    source_meta = None
    if source_url:
        source_meta = {
            "agentId": agent_id,
            "skillName": skill_name,
            "sourceUrl": source_url,
            "description": description,
            "checksum": _checksum(content),
            "installedAt": _utc_now(),
            "runtime": "hermes",
        }
        (target_dir / ".source.json").write_text(json.dumps(source_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    _sync_agent_config()
    return {
        "ok": True,
        "agentId": agent_id,
        "skillName": skill_name,
        "source": source_url or "local",
        "localPath": str(target),
        "size": len(content.encode("utf-8")),
        "checksum": _checksum(content),
        "addedAt": _utc_now(),
        "sourceMeta": source_meta,
    }


def _court_store_path() -> Path:
    return _data_dir() / "court_sessions.json"


def _load_court_sessions() -> dict[str, dict[str, Any]]:
    path = _court_store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_court_sessions(sessions: dict[str, dict[str, Any]]) -> None:
    _court_store_path().write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")


def _court_official(agent_id: str) -> dict[str, str]:
    meta = AGENT_META.get(agent_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown official: {agent_id}")
    personality, speaking_style = COURT_DETAILS.get(agent_id, ("沉稳可靠。", "简洁陈述观点。"))
    return {
        "id": agent_id,
        "name": meta["label"],
        "emoji": meta["emoji"],
        "role": meta["role"],
        "duty": meta["duty"],
        "personality": personality,
        "speaking_style": speaking_style,
    }


def _court_system_message(content: str) -> dict[str, Any]:
    return {"type": "system", "content": content, "timestamp": time.time()}


def _court_scene_note(round_no: int, has_decree: bool) -> str:
    if has_decree:
        return f"第 {round_no} 轮，天命入殿，群臣先应新局，再回到议题。"
    return f"第 {round_no} 轮，群臣依职责陈奏，议题继续收束。"


def _simulate_court_messages(session: dict[str, Any], user_message: str | None, decree: str | None) -> list[dict[str, Any]]:
    round_no = int(session.get("round") or 1)
    topic = session.get("topic", "")
    messages = []
    for idx, official in enumerate(session.get("officials", [])):
        oid = official["id"]
        pool = COURT_RESPONSE_TEMPLATES.get(oid) or ["臣附议，但请先明确定义验收标准。"]
        content = pool[(round_no + idx) % len(pool)]
        if decree:
            content = f"天命既降，臣先按“{decree[:40]}”调整判断。{content}"
        elif user_message:
            content = f"回禀陛下，针对“{user_message[:40]}”，{content}"
        else:
            content = f"围绕“{topic[:40]}”，{content}"
        messages.append(
            {
                "official_id": oid,
                "name": official["name"],
                "content": content,
                "emotion": random.choice(["neutral", "confident", "thinking", "worried", "amused"]),
                "action": None,
            }
        )
    return messages


def _court_history_excerpt(session: dict[str, Any]) -> str:
    lines = []
    for msg in session.get("messages", [])[-10:]:
        msg_type = msg.get("type", "")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if msg_type == "official":
            speaker = msg.get("official_name") or msg.get("name") or msg.get("official_id") or "官员"
        elif msg_type == "emperor":
            speaker = "皇帝"
        elif msg_type == "decree":
            speaker = "天命"
        else:
            speaker = "旁白"
        lines.append(f"- {speaker}: {content[:240]}")
    return "\n".join(lines) if lines else "- 暂无前情"


def _build_court_prompt(
    official: dict[str, Any],
    session: dict[str, Any],
    user_message: str | None,
    decree: str | None,
) -> str:
    additions = []
    if user_message:
        additions.append(f"皇帝刚才发言：{user_message}")
    if decree:
        additions.append(f"天命/随机事件：{decree}")
    current_signal = "\n".join(additions) if additions else "本轮无额外圣谕，请围绕议题继续推进。"
    return f"""你正在参加“三省六部”的朝堂议政。Hermes profile 已代表你的身份，请保持该 profile 的口吻。

议题：{session.get("topic", "")}
你的官职：{official.get("name", "")} / {official.get("role", "")}
你的职责：{official.get("duty", "")}

最近议政记录：
{_court_history_excerpt(session)}

本轮信号：
{current_signal}

请只输出你这一位官员的奏议正文：
- 中文
- 1 到 3 句
- 必须给出一个具体判断或建议
- 不要调用工具，不要写 JSON，不要列标题，不要解释你是 AI
"""


def _clean_hermes_court_output(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned[:900]


def _call_hermes_court_official(
    official: dict[str, Any],
    session: dict[str, Any],
    user_message: str | None,
    decree: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    _ensure_profile_runtime_config(official["id"])
    prompt = _build_court_prompt(official, session, user_message, decree)
    cmd = [
        settings.hermes_bin,
        "--profile",
        official["id"],
        "--accept-hooks",
    ]
    if settings.hermes_model:
        cmd.extend(["--model", settings.hermes_model])
    if settings.hermes_provider:
        cmd.extend(["--provider", settings.hermes_provider])
    court_toolsets = os.environ.get("COURT_HERMES_TOOLSETS") or settings.hermes_toolsets
    if court_toolsets:
        cmd.extend(["--toolsets", court_toolsets])
    cmd.extend(["--oneshot", prompt])

    env = os.environ.copy()
    env["HERMES_HOME"] = str(_hermes_home())
    env["HERMES_PROJECT_DIR"] = settings.hermes_project_dir or str(_project_root())
    env["HERMES_SOURCE"] = settings.hermes_source
    env["EDICT_COURT_SESSION_ID"] = session.get("session_id", "")
    env["EDICT_COURT_TOPIC"] = session.get("topic", "")

    timeout = int(os.environ.get("COURT_HERMES_TIMEOUT_SEC", "120"))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=settings.hermes_project_dir or str(_project_root()),
    )
    content = _clean_hermes_court_output(proc.stdout)
    if proc.returncode != 0 or not content:
        error = (proc.stderr or proc.stdout or "Hermes returned empty output").strip()[-500:]
        raise RuntimeError(error)
    return {
        "official_id": official["id"],
        "name": official["name"],
        "content": content,
        "emotion": "confident",
        "action": None,
        "runtime": "hermes",
    }


async def _call_hermes_court_messages(
    session: dict[str, Any],
    user_message: str | None,
    decree: str | None,
) -> list[dict[str, Any]]:
    max_concurrency = max(1, int(os.environ.get("COURT_HERMES_CONCURRENCY", "2")))
    semaphore = asyncio.Semaphore(max_concurrency)
    fallback = _simulate_court_messages(session, user_message, decree)
    fallback_by_id = {msg["official_id"]: msg for msg in fallback}

    async def _one(official: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                return await asyncio.to_thread(_call_hermes_court_official, official, session, user_message, decree)
            except Exception as exc:
                msg = dict(fallback_by_id.get(official["id"]) or {})
                msg["runtime"] = "fallback"
                msg["error"] = str(exc)[-300:]
                return msg

    return await asyncio.gather(*[_one(official) for official in session.get("officials", [])])


def _court_summary(session: dict[str, Any]) -> str:
    official_names = "、".join(o["name"] for o in session.get("officials", []))
    official_messages = [m for m in session.get("messages", []) if m.get("type") == "official"]
    rounds = session.get("round", 0)
    return (
        f"议题“{session.get('topic', '')}”已议至第 {rounds} 轮。"
        f"{official_names}均已陈奏，共形成 {len(official_messages)} 条意见。"
        "建议下一步按“目标、负责人、验收、回滚”四项整理成可执行旨意。"
    )


def _task_display(task: Task) -> dict[str, Any]:
    data = task.to_dict()
    legacy_id = (task.meta or {}).get("legacy_id")
    if legacy_id:
        data["id"] = legacy_id
    state = _task_state(task)
    if state == TaskState.Done and not data.get("output"):
        data["output"] = _latest_progress_text(task, ("shangshu", "libu"))
    if state == TaskState.Done:
        data["heartbeat"] = {"status": "active", "label": "已完成"}
    elif state == TaskState.Cancelled:
        data["heartbeat"] = {"status": "unknown", "label": "已取消"}
    else:
        data["heartbeat"] = data.get("heartbeat") or {"status": "idle", "label": "待命"}
    return data


async def _task_service(db: AsyncSession) -> TaskService:
    return TaskService(db, await get_event_bus())


async def _find_task(db: AsyncSession, raw_id: str) -> Task:
    try:
        task = await db.get(Task, uuid.UUID(raw_id))
        if task:
            return task
    except ValueError:
        pass

    stmt = select(Task).where(Task.tags.contains([raw_id]))
    result = await db.execute(stmt)
    task = result.scalars().first()
    if task:
        return task

    stmt = select(Task).where(Task.meta["legacy_id"].astext == raw_id)
    result = await db.execute(stmt)
    task = result.scalars().first()
    if task:
        return task
    raise HTTPException(status_code=404, detail=f"Task not found: {raw_id}")


async def _set_state_direct(db: AsyncSession, task: Task, state: TaskState, agent: str, reason: str) -> None:
    old = task.state.value if isinstance(task.state, TaskState) else str(task.state)
    task.state = state
    task.org = Task.org_for_state(state, task.assignee_org)
    if reason:
        task.now = reason
    task.updated_at = datetime.now(timezone.utc)
    entry = {
        "at": task.updated_at.isoformat(),
        "from": old,
        "to": state.value,
        "agent": agent,
        "remark": reason,
    }
    task.flow_log = [*(task.flow_log or []), entry]
    await db.commit()


@router.get("/live-status")
async def live_status(db: AsyncSession = Depends(get_db)):
    svc = await _task_service(db)
    tasks = await svc.list_tasks(limit=200)
    task_rows = [_task_display(t) for t in tasks]
    return {
        "tasks": task_rows,
        "completed_tasks": {
            t["id"]: t for t in task_rows if t.get("state") in {s.value for s in TERMINAL_STATES}
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "syncStatus": {"ok": True, "runtime": "hermes", "backend": "edict"},
    }


@router.get("/agent-config")
async def agent_config():
    cfg = _read_json("agent_config.json", {})
    if isinstance(cfg, dict) and isinstance(cfg.get("agents"), list) and cfg["agents"]:
        return cfg
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runtime": "hermes",
        "dispatchChannel": cfg.get("dispatchChannel", "") if isinstance(cfg, dict) else "",
        "knownModels": KNOWN_MODELS,
        "agents": [
            {
                "id": agent_id,
                **meta,
                "model": "",
                "defaultModel": "",
                "workspace": "",
                "profile": "",
                "profileExists": False,
                "skills": [],
                "runtime": "hermes",
            }
            for agent_id, meta in AGENT_META.items()
        ],
    }


@router.get("/model-change-log")
async def model_change_log():
    return _read_json("model_change_log.json", [])


@router.get("/hermes-profile-status")
async def hermes_profile_status():
    _sync_agent_config()
    cfg = _read_json("agent_config.json", {})
    agents = cfg.get("agents", []) if isinstance(cfg, dict) else []
    by_id = {agent.get("id"): agent for agent in agents if isinstance(agent, dict) and agent.get("id")}
    agent_ids = [agent_id for agent_id in AGENT_META if agent_id in by_id] or list(AGENT_META)
    return {
        "ok": True,
        "runtime": "hermes",
        "hermesHome": str(_hermes_home()),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "agents": [_profile_status(agent_id, by_id.get(agent_id)) for agent_id in agent_ids],
    }


@router.post("/hermes-profile-test")
async def hermes_profile_test(body: ProfileTestBody):
    agent_id = _validate_agent_id(body.agentId)
    _ensure_profile_runtime_config(agent_id)
    prompt = (body.prompt or "只回复：Hermes OK").strip()[:500]
    settings = get_settings()
    cmd = [
        settings.hermes_bin,
        "--profile",
        agent_id,
        "chat",
        "--quiet",
        "--source",
        settings.hermes_source,
        "-q",
        prompt,
    ]
    env = os.environ.copy()
    env["HERMES_HOME"] = str(_hermes_home())
    env["HERMES_PROJECT_DIR"] = settings.hermes_project_dir or str(_project_root())
    env["HERMES_SOURCE"] = settings.hermes_source
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("HERMES_PROFILE_TEST_TIMEOUT_SEC", "60")),
            env=env,
            cwd=settings.hermes_project_dir or str(_project_root()),
        )
    except FileNotFoundError:
        return {"ok": False, "agentId": agent_id, "error": f"Hermes CLI not found: {settings.hermes_bin}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "agentId": agent_id, "error": "Hermes profile test timed out"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    return {
        "ok": proc.returncode == 0,
        "agentId": agent_id,
        "returncode": proc.returncode,
        "elapsedSec": round(time.time() - started, 2),
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
        "command": " ".join(cmd[:-1] + ["<prompt>"]),
        "message": "Hermes profile 可用" if proc.returncode == 0 else "Hermes profile 测试失败",
    }


@router.get("/officials-stats")
async def officials_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).order_by(Task.updated_at.desc()).limit(1000))
    return _merge_runtime_official_stats(_build_officials_from_tasks(list(result.scalars().all())))


@router.get("/agents-status")
async def agents_status(db: AsyncSession = Depends(get_db)):
    checked_at = datetime.now(timezone.utc).isoformat()
    result = await db.execute(select(Task).order_by(Task.updated_at.desc()).limit(1000))
    stats = _build_officials_from_tasks(list(result.scalars().all()))
    by_agent = {row["id"]: row for row in stats["officials"]}

    def status_for(agent_id: str) -> tuple[str, str]:
        profile_exists = _profile_dir(agent_id).exists()
        if not profile_exists:
            return "unconfigured", "Hermes profile 未初始化"
        heartbeat = (by_agent.get(agent_id) or {}).get("heartbeat", {})
        raw_status = heartbeat.get("status", "idle")
        label = heartbeat.get("label", "")
        if raw_status == "active":
            return "running", label or "任务处理中"
        if raw_status == "unknown":
            return "offline", label or "状态未知"
        return "idle", label or "Hermes profile 待命"

    def agent_row(agent_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        status, label = status_for(agent_id)
        return {
            "id": agent_id,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "role": meta["role"],
            "status": status,
            "statusLabel": label,
            "lastActive": (by_agent.get(agent_id) or {}).get("last_active") or "",
            "profileExists": status != "unconfigured",
        }

    return {
        "ok": True,
        "gateway": {"alive": True, "probe": True, "status": "hermes-dispatcher"},
        "agents": [agent_row(agent_id, meta) for agent_id, meta in AGENT_META.items()],
        "checkedAt": checked_at,
    }


@router.get("/morning-brief")
async def morning_brief():
    return _read_json("morning_brief.json", {"categories": {}})


@router.get("/morning-config")
async def morning_config():
    return _read_json(
        "morning_brief_config.json",
        {
            "categories": [
                {"name": "政治", "enabled": True},
                {"name": "军事", "enabled": True},
                {"name": "经济", "enabled": True},
                {"name": "AI大模型", "enabled": True},
            ],
            "keywords": [],
            "custom_feeds": [],
            "feishu_webhook": "",
        },
    )


@router.post("/morning-config")
async def save_morning_config(body: dict[str, Any]):
    _write_json("morning_brief_config.json", body)
    return {"ok": True, "message": "订阅配置已保存"}


@router.post("/morning-brief/refresh")
async def refresh_morning():
    return {"ok": True, "message": "已收到刷新请求；当前 Docker 轻量模式未启动新闻采集任务"}


@router.get("/remote-skills-list")
async def remote_skills_list():
    remote_skills = []
    cfg = _read_json("agent_config.json", {})
    agent_ids = [a["id"] for a in cfg.get("agents", []) if isinstance(a, dict) and a.get("id")]
    if not agent_ids:
        agent_ids = list(AGENT_META)
    for agent_id in agent_ids:
        skills_dir = _profile_dir(agent_id) / "skills"
        if not skills_dir.exists():
            continue
        for meta_path in sorted(skills_dir.glob("*/.source.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            skill_file = meta_path.parent / "SKILL.md"
            remote_skills.append(
                {
                    "agentId": agent_id,
                    "skillName": meta.get("skillName") or meta_path.parent.name,
                    "sourceUrl": meta.get("sourceUrl", ""),
                    "description": meta.get("description", ""),
                    "checksum": meta.get("checksum", ""),
                    "installedAt": meta.get("installedAt", ""),
                    "updatedAt": meta.get("updatedAt", ""),
                    "localPath": str(skill_file),
                    "exists": skill_file.exists(),
                    "runtime": "hermes",
                }
            )
    return {"ok": True, "remoteSkills": remote_skills, "count": len(remote_skills), "listedAt": _utc_now()}


@router.get("/skill-content/{agent_id}/{skill_name}")
async def skill_content(agent_id: str, skill_name: str):
    agent_id = _validate_safe_name(agent_id, "agentId")
    skill_name = _validate_safe_name(skill_name, "skillName")
    base = _project_root() / "agents" / agent_id / "skills"
    candidates = [
        _profile_skill_dir(agent_id, skill_name) / "SKILL.md",
        base / skill_name,
        base / f"{skill_name}.md",
        base / skill_name / "SKILL.md",
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return {"ok": True, "agent": agent_id, "name": skill_name, "path": str(path), "content": path.read_text(encoding="utf-8")}
    return {"ok": False, "error": "skill not found"}


@router.get("/task-activity/{task_id}")
async def task_activity(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await _find_task(db, task_id)
    activity = []
    for item in task.flow_log or []:
        activity.append({"kind": "flow", **item})
    for item in task.progress_log or []:
        activity.append({"kind": "progress", **item})
    return {"ok": True, "activity": activity, "relatedAgents": [], "lastActive": task.updated_at.isoformat()}


@router.get("/scheduler-state/{task_id}")
async def scheduler_state(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await _find_task(db, task_id)
    return {"ok": True, "scheduler": task.scheduler or {}, "stalledSec": 0}


@router.post("/create-task")
async def create_task(body: CreateTaskBody, db: AsyncSession = Depends(get_db)):
    svc = await _task_service(db)
    legacy_id = f"JJC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    execution_org = _infer_execution_org(body.title, body.params, body.targetDept)
    task = await svc.create_task(
        title=body.title,
        description="",
        priority=body.priority,
        assignee_org=execution_org,
        creator="emperor",
        tags=[legacy_id, "dashboard"],
        meta={
            "legacy_id": legacy_id,
            "templateId": body.templateId,
            "params": body.params,
            "requestedTargetDept": body.targetDept,
            "inferredExecutionOrg": execution_org,
        },
    )
    task.target_dept = execution_org or body.targetDept or ""
    await db.commit()
    return {"ok": True, "taskId": legacy_id, "uuid": str(task.task_id), "message": "旨意已下发给太子"}


@router.post("/task-action")
async def task_action(body: TaskActionBody, db: AsyncSession = Depends(get_db)):
    task = await _find_task(db, body.taskId)
    reason = body.reason or f"皇上从看板{body.action}"
    if body.action == "cancel":
        await _set_state_direct(db, task, TaskState.Cancelled, "dashboard", reason)
    elif body.action == "stop":
        await _set_state_direct(db, task, TaskState.Blocked, "dashboard", reason)
    elif body.action == "resume":
        await _set_state_direct(db, task, TaskState.Taizi, "dashboard", reason)
    else:
        raise HTTPException(status_code=400, detail="action must be stop/cancel/resume")
    return {"ok": True, "message": "状态已更新"}


@router.post("/review-action")
async def review_action(body: ReviewActionBody, db: AsyncSession = Depends(get_db)):
    task = await _find_task(db, body.taskId)
    target = TaskState.Done if body.action == "approve" else TaskState.Menxia
    await _set_state_direct(db, task, target, "dashboard", body.comment or body.action)
    return {"ok": True, "message": "审阅结果已记录"}


@router.post("/advance-state")
async def advance_state(body: AdvanceStateBody, db: AsyncSession = Depends(get_db)):
    order = [
        TaskState.Taizi,
        TaskState.Zhongshu,
        TaskState.Menxia,
        TaskState.Assigned,
        TaskState.Doing,
        TaskState.Review,
        TaskState.Done,
    ]
    task = await _find_task(db, body.taskId)
    current = task.state if isinstance(task.state, TaskState) else TaskState(str(task.state))
    target = order[min(order.index(current) + 1, len(order) - 1)] if current in order else TaskState.Taizi
    await _set_state_direct(db, task, target, "dashboard", body.comment or "手动推进")
    return {"ok": True, "message": f"已推进到 {target.value}"}


@router.post("/archive-task")
async def archive_task(body: ArchiveTaskBody, db: AsyncSession = Depends(get_db)):
    if body.archiveAllDone:
        stmt = select(Task).where(Task.state.in_([TaskState.Done, TaskState.Cancelled]))
        result = await db.execute(stmt)
        tasks = list(result.scalars().all())
        for task in tasks:
            task.archived = True
        await db.commit()
        return {"ok": True, "count": len(tasks)}
    if not body.taskId:
        raise HTTPException(status_code=400, detail="taskId required")
    task = await _find_task(db, body.taskId)
    task.archived = body.archived
    await db.commit()
    return {"ok": True, "message": "归档状态已更新"}


@router.post("/agent-wake")
async def agent_wake(body: AgentWakeBody):
    return {"ok": True, "message": f"{body.agentId} 已在 Hermes dispatcher 中待命"}


@router.post("/set-model")
async def set_model(body: ModelBody):
    cfg = _read_json("agent_config.json", {})
    changes = _read_json("model_change_log.json", [])
    changes.append({
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "agentId": body.agentId,
        "oldModel": "",
        "newModel": body.model,
    })
    _write_json("model_change_log.json", changes[-100:])
    if isinstance(cfg, dict):
        for agent in cfg.get("agents", []):
            if agent.get("id") == body.agentId:
                agent["model"] = body.model
        _write_json("agent_config.json", cfg)
    return {"ok": True, "message": "看板配置已记录；实际推理模型仍以 Hermes profile/config.yaml 为准"}


@router.post("/set-dispatch-channel")
async def set_dispatch_channel(body: DispatchChannelBody):
    cfg = _read_json("agent_config.json", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg["dispatchChannel"] = body.channel
    _write_json("agent_config.json", cfg)
    return {"ok": True, "message": f"派发渠道已切换为 {body.channel}"}


@router.post("/add-skill")
async def add_skill(body: AddSkillBody):
    skill_name = _validate_safe_name(body.skillName, "skillName")
    description = body.description.strip() or f"{skill_name} skill for Hermes profile {body.agentId}"
    trigger = body.trigger.strip() or "Use this skill when the user asks for this capability."
    content = f"""---
name: {skill_name}
description: {description}
---

# {skill_name}

{description}

## When To Use

{trigger}

## Instructions

- Follow the current Hermes profile instructions.
- Keep output focused on the user's task.
"""
    result = _install_skill(body.agentId, skill_name, content, description=description)
    result["message"] = "本地技能已写入 Hermes profile 并同步配置"
    return result


@router.post("/add-remote-skill")
async def add_remote_skill(body: AddRemoteSkillBody):
    content, source = _read_source_text(body.sourceUrl)
    result = _install_skill(body.agentId, body.skillName, content, source_url=source, description=body.description)
    result["message"] = "远程技能已安装到 Hermes profile"
    return result


@router.post("/update-remote-skill")
async def update_remote_skill(body: RemoteSkillBody):
    agent_id = _validate_agent_id(body.agentId)
    skill_name = _validate_safe_name(body.skillName, "skillName")
    meta_path = _profile_skill_dir(agent_id, skill_name) / ".source.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="remote skill source metadata not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source_url = meta.get("sourceUrl")
    if not source_url:
        raise HTTPException(status_code=400, detail="remote skill has no sourceUrl")
    content, source = _read_source_text(source_url)
    result = _install_skill(agent_id, skill_name, content, source_url=source, description=meta.get("description", ""))
    new_meta_path = _profile_skill_dir(agent_id, skill_name) / ".source.json"
    new_meta = json.loads(new_meta_path.read_text(encoding="utf-8"))
    new_meta["installedAt"] = meta.get("installedAt") or new_meta.get("installedAt")
    new_meta["updatedAt"] = _utc_now()
    new_meta_path.write_text(json.dumps(new_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    result["message"] = "远程技能已从来源更新"
    result["updatedAt"] = new_meta["updatedAt"]
    return result


@router.post("/remove-remote-skill")
async def remove_remote_skill(body: RemoteSkillBody):
    agent_id = _validate_agent_id(body.agentId)
    skill_name = _validate_safe_name(body.skillName, "skillName")
    target_dir = _profile_skill_dir(agent_id, skill_name)
    meta_path = target_dir / ".source.json"
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="skill not found")
    if not meta_path.exists():
        raise HTTPException(status_code=400, detail="refusing to remove a local skill through remote skill API")
    shutil.rmtree(target_dir)
    _sync_agent_config()
    return {"ok": True, "message": "远程技能已从 Hermes profile 删除", "agentId": agent_id, "skillName": skill_name}


@router.post("/scheduler-scan")
async def scheduler_scan():
    return {"ok": True, "count": 0, "actions": [], "checkedAt": datetime.now(timezone.utc).isoformat()}


@router.post("/scheduler-retry")
async def scheduler_retry():
    return {"ok": True, "message": "轻量调度器已接收"}


@router.post("/scheduler-escalate")
async def scheduler_escalate():
    return {"ok": True, "message": "轻量调度器已接收"}


@router.post("/scheduler-rollback")
async def scheduler_rollback():
    return {"ok": True, "message": "轻量调度器已接收"}


@router.post("/court-discuss/start")
async def court_start(body: CourtStartBody):
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic required")
    official_ids = []
    for oid in body.officials:
        cleaned = _validate_safe_name(oid, "official")
        if cleaned not in official_ids:
            official_ids.append(cleaned)
    if len(official_ids) < 2:
        raise HTTPException(status_code=400, detail="at least 2 officials required")
    officials = [_court_official(oid) for oid in official_ids]
    session_id = uuid.uuid4().hex[:8]
    session = {
        "session_id": session_id,
        "topic": topic,
        "task_id": body.taskId,
        "officials": officials,
        "messages": [_court_system_message(f"朝堂议政开启：{topic}")],
        "round": 0,
        "phase": "discussing",
        "runtime": "hermes",
        "createdAt": _utc_now(),
        "updatedAt": _utc_now(),
    }
    sessions = _load_court_sessions()
    sessions[session_id] = session
    _save_court_sessions(sessions)
    return {"ok": True, **session}


@router.post("/court-discuss/advance")
async def court_advance(body: CourtAdvanceBody):
    sessions = _load_court_sessions()
    session = sessions.get(body.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="court session not found")
    if session.get("phase") == "concluded":
        raise HTTPException(status_code=400, detail="court session already concluded")

    user_message = (body.userMessage or "").strip()
    decree = (body.decree or "").strip()
    if user_message:
        session["messages"].append({"type": "emperor", "content": user_message, "timestamp": time.time()})
    if decree:
        session["messages"].append({"type": "decree", "content": decree, "timestamp": time.time()})

    session["round"] = int(session.get("round") or 0) + 1
    hermes_enabled = os.environ.get("COURT_HERMES_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    if hermes_enabled:
        new_messages = await _call_hermes_court_messages(session, user_message or None, decree or None)
    else:
        new_messages = _simulate_court_messages(session, user_message or None, decree or None)
    for msg in new_messages:
        session["messages"].append(
            {
                "type": "official",
                "official_id": msg["official_id"],
                "official_name": msg["name"],
                "content": msg["content"],
                "emotion": msg["emotion"],
                "action": msg["action"],
                "runtime": msg.get("runtime", "simulated"),
                "error": msg.get("error"),
                "timestamp": time.time(),
            }
        )
    hermes_count = len([m for m in new_messages if m.get("runtime") == "hermes"])
    fallback_count = len([m for m in new_messages if m.get("runtime") == "fallback"])
    scene_note = _court_scene_note(session["round"], bool(decree))
    if hermes_enabled:
        scene_note += f" Hermes 调用 {hermes_count}/{len(new_messages)} 位官员"
        if fallback_count:
            scene_note += f"，{fallback_count} 位暂用轻量备用。"
        else:
            scene_note += "。"
    session["messages"].append({"type": "scene_note", "content": scene_note, "timestamp": time.time()})
    session["updatedAt"] = _utc_now()
    sessions[body.sessionId] = session
    _save_court_sessions(sessions)
    return {
        "ok": True,
        "session_id": body.sessionId,
        "round": session["round"],
        "new_messages": new_messages,
        "scene_note": scene_note,
        "total_messages": len(session["messages"]),
    }


@router.post("/court-discuss/conclude")
async def court_conclude(body: CourtSessionBody):
    sessions = _load_court_sessions()
    session = sessions.get(body.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="court session not found")
    summary = _court_summary(session)
    session["phase"] = "concluded"
    session["summary"] = summary
    session["updatedAt"] = _utc_now()
    session["messages"].append(_court_system_message(f"散朝：{summary}"))
    sessions[body.sessionId] = session
    _save_court_sessions(sessions)
    return {"ok": True, "session_id": body.sessionId, "summary": summary, "message": "议政已结束"}


@router.post("/court-discuss/destroy")
async def court_destroy(body: CourtSessionBody):
    sessions = _load_court_sessions()
    removed = sessions.pop(body.sessionId, None)
    _save_court_sessions(sessions)
    return {"ok": True, "removed": bool(removed)}


@router.get("/court-discuss/fate")
async def court_fate():
    return {"ok": True, "event": random.choice(FATE_EVENTS)}
