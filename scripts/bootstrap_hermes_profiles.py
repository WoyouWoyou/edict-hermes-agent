#!/usr/bin/env python3
"""Bootstrap Hermes profiles for the Edict multi-agent court."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys


BASE = pathlib.Path(__file__).resolve().parent.parent
AGENTS_DIR = BASE / "agents"

AGENT_IDS = (
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
)

GROUP_MAP = {
    "taizi": "sansheng",
    "zhongshu": "sansheng",
    "menxia": "sansheng",
    "shangshu": "sansheng",
    "hubu": "liubu",
    "libu": "liubu",
    "bingbu": "liubu",
    "xingbu": "liubu",
    "gongbu": "liubu",
    "libu_hr": "liubu",
}


def hermes_root(hermes_home: str | None) -> pathlib.Path:
    if hermes_home:
        path = pathlib.Path(hermes_home).expanduser()
    else:
        path = pathlib.Path.home() / ".hermes"
    if path.parent.name == "profiles":
        return path.parent.parent
    return path


def profile_dir(root: pathlib.Path, agent_id: str) -> pathlib.Path:
    return root / "profiles" / agent_id


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_soul(agent_id: str) -> str:
    parts = []
    global_md = read_text(AGENTS_DIR / "GLOBAL.md")
    if global_md:
        parts.append(global_md)

    group = GROUP_MAP.get(agent_id)
    if group:
        group_md = read_text(AGENTS_DIR / "groups" / f"{group}.md")
        if group_md:
            parts.append(group_md)

    agent_md = read_text(AGENTS_DIR / agent_id / "SOUL.md")
    if agent_md:
        parts.append(agent_md)

    return "\n\n---\n\n".join(parts).strip() + "\n"


def create_profile(hermes_bin: str, agent_id: str, env: dict[str, str], dry_run: bool) -> None:
    cmd = [hermes_bin, "profile", "create", agent_id, "--no-alias"]
    if dry_run:
        print("+ " + " ".join(cmd))
        return
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 and "already exists" not in (result.stderr + result.stdout):
        raise RuntimeError(
            f"Failed to create Hermes profile {agent_id}: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def sync_profile_soul(root: pathlib.Path, agent_id: str, dry_run: bool) -> None:
    destination = profile_dir(root, agent_id) / "SOUL.md"
    content = build_soul(agent_id)
    if not content.strip():
        raise RuntimeError(f"No SOUL.md content found for agent {agent_id}")
    if dry_run:
        print(f"write {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def find_config_source(root: pathlib.Path, target_agent_id: str, preferred: str | None) -> pathlib.Path | None:
    candidates = [preferred or "", os.environ.get("HERMES_CONFIG_SOURCE_PROFILE", ""), "taizi"]
    for agent_id in candidates:
        if not agent_id or agent_id == target_agent_id:
            continue
        candidate = profile_dir(root, agent_id)
        if (candidate / "config.yaml").exists() or (candidate / ".env").exists():
            return candidate
    profiles_root = root / "profiles"
    if profiles_root.exists():
        for candidate in sorted(profiles_root.iterdir()):
            if candidate.name == target_agent_id or not candidate.is_dir():
                continue
            if (candidate / "config.yaml").exists() or (candidate / ".env").exists():
                return candidate
    return None


def sync_runtime_config(root: pathlib.Path, agent_id: str, preferred_source: str | None, dry_run: bool) -> None:
    destination = profile_dir(root, agent_id)
    source = find_config_source(root, agent_id, preferred_source)
    if not source:
        return
    for name in ("config.yaml", ".env"):
        src = source / name
        dst = destination / name
        if not src.exists() or dst.exists():
            continue
        if dry_run:
            print(f"copy {src} -> {dst}")
            continue
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and sync Edict Hermes profiles.")
    parser.add_argument("--hermes-bin", default=os.environ.get("HERMES_BIN", "hermes"))
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME"))
    parser.add_argument("--agents", nargs="*", default=list(AGENT_IDS))
    parser.add_argument("--config-source-profile", default=os.environ.get("HERMES_CONFIG_SOURCE_PROFILE"))
    parser.add_argument("--skip-create", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = hermes_root(args.hermes_home)
    env = os.environ.copy()
    env["HERMES_HOME"] = str(root)

    for agent_id in args.agents:
        if agent_id not in AGENT_IDS:
            raise RuntimeError(f"Unknown Edict agent: {agent_id}")
        if not args.skip_create:
            create_profile(args.hermes_bin, agent_id, env, args.dry_run)
        sync_profile_soul(root, agent_id, args.dry_run)
        sync_runtime_config(root, agent_id, args.config_source_profile, args.dry_run)
        print(f"synced Hermes profile: {agent_id}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
