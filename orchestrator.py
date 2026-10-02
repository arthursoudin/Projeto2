"""Jarvis V13.0 — Core Integrado.

Camada leve de coordenação usada pelo Dashboard/Gateway. Não executa ações do
computador por conta própria: apenas organiza estado, eventos e missões e
mantém um contrato único para os componentes já existentes.
"""
from __future__ import annotations
import secrets
from datetime import datetime, timezone
import store

VERSION = "14.5.2"
EVENT_LIMIT = 300
MISSION_LIMIT = 100

COMPONENTS = {
    "brain": "Cérebro / roteamento",
    "planner": "Planejador multiagente",
    "memory": "Memória",
    "tasks": "Tarefas",
    "skills": "Skills",
    "tools": "Tools",
    "computer_agent": "Computer Agent",
    "local_agent": "Agente local do PC",
    "whatsapp": "WhatsApp",
    "voice": "Voz",
    "security": "Segurança e permissões",
    "overnight_lab": "Laboratório Noturno",
}

def _now():
    return datetime.now(timezone.utc).isoformat()

def _clean(value, depth=0):
    if depth > 2:
        return str(value)[:300]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value if not isinstance(value, str) else value[:500]
    if isinstance(value, dict):
        return {str(k)[:60]: _clean(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in list(value)[:20]]
    return str(value)[:500]

def events():
    data = store.load("system_timeline", [])
    return data[-EVENT_LIMIT:] if isinstance(data, list) else []

def record_event(event, source="system", status="info", **data):
    row = {
        "id": secrets.token_urlsafe(10),
        "timestamp": _now(),
        "event": str(event)[:120],
        "source": str(source)[:80],
        "status": str(status)[:30],
        "data": _clean(data),
    }
    rows = events()
    rows.append(row)
    store.save("system_timeline", rows[-EVENT_LIMIT:])
    return row

def component_status(agent_status=None, security_status=None, whatsapp_status=None):
    """Retorna uma visão única do estado sem fazer chamadas externas."""
    out = {}
    if agent_status:
        out["local_agent"] = {
            "online": bool(agent_status.get("online")),
            "info": agent_status.get("info") or {},
        }
    if security_status:
        out["security"] = {
            "enabled": bool(security_status.get("policy", {}).get("enabled", True)),
            "kill_switch": bool(security_status.get("kill_switch")),
            "pending": int(security_status.get("pending", 0) or 0),
        }
    if whatsapp_status:
        out["whatsapp"] = {
            "configured": bool(whatsapp_status.get("configured")),
            "messages_today": int(whatsapp_status.get("messages_today", 0) or 0),
        }
    return out

def status(agent_status=None, security_status=None, whatsapp_status=None):
    missions = list_missions()
    active = [m for m in missions if m.get("status") == "running"]
    return {
        "ok": True,
        "version": VERSION,
        "components": list(COMPONENTS.keys()),
        "component_names": COMPONENTS,
        "runtime": component_status(agent_status, security_status, whatsapp_status),
        "missions": {
            "total": len(missions),
            "running": len(active),
            "last": missions[-1] if missions else None,
        },
        "timeline": {
            "entries": len(events()),
            "last": events()[-1] if events() else None,
        },
    }

def list_missions():
    data = store.load("missions", [])
    return data[-MISSION_LIMIT:] if isinstance(data, list) else []

def create_mission(goal, source="app"):
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("Objetivo da missão não pode ser vazio.")
    item = {
        "id": "mission_" + secrets.token_urlsafe(8),
        "goal": goal[:1000],
        "source": str(source)[:80],
        "status": "running",
        "created_at": _now(),
        "updated_at": _now(),
        "steps": [],
    }
    rows = list_missions()
    rows.append(item)
    store.save("missions", rows[-MISSION_LIMIT:])
    record_event("mission_created", source=source, mission_id=item["id"], status="running", goal=goal[:300])
    return item

def update_mission(mission_id, status=None, steps=None, result=None):
    rows = list_missions()
    found = None
    for item in rows:
        if item.get("id") == mission_id:
            found = item
            break
    if not found:
        return None
    if status:
        found["status"] = str(status)[:30]
    if steps is not None:
        found["steps"] = _clean(steps)
    if result is not None:
        found["result"] = _clean(result)
    found["updated_at"] = _now()
    store.save("missions", rows[-MISSION_LIMIT:])
    record_event(
        "mission_updated",
        source=found.get("source", "system"),
        mission_id=mission_id,
        status=found.get("status"),
    )
    return found

def finish_mission(mission_id, ok, result=None):
    return update_mission(
        mission_id,
        status="completed" if ok else "failed",
        result=result,
    )

def capabilities():
    return {
        "version": VERSION,
        "core": ["routing", "multiagent", "memory", "tasks", "tools", "computer_agent"],
        "channels": ["dashboard", "whatsapp"],
        "security": ["risk", "approval", "audit", "kill_switch", "limits"],
        "foundation": ["timeline", "missions", "component_status"],
        "future_ready": ["file_manager", "document_manager", "app_agents", "workflows"],
        "device_app_control": ["multi_pc", "device_manager", "app_inventory", "safe_app_launch"],
        "live_operations": ["operation_id", "agent_state", "duration_ms", "current_action", "result_preview"],
    }
