"""Jarvis Core 2.0 — estado e contratos compartilhados entre memória, PC, tasks e automações."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json

CORE_VERSION = "12.4"
STATE_FILE = Path('.jarvis_core.json')

@dataclass
class SystemState:
    core_version: str = CORE_VERSION
    gateway: str = 'unknown'
    local_agent: str = 'offline'
    honcho: str = 'unknown'
    last_heartbeat: str = ''
    active_session: str = ''


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8')) if STATE_FILE.exists() else {}
        return SystemState(**{k: data.get(k, v) for k, v in asdict(SystemState()).items()})
    except Exception:
        return SystemState()


def save_state(state):
    STATE_FILE.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding='utf-8')


def mark_agent_online():
    state = load_state()
    state.local_agent = 'online'
    state.last_heartbeat = now_iso()
    save_state(state)
    return state
