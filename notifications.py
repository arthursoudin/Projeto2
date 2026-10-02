"""JARVIS V13.4 — Notification Center.

Builds compact, read-only notifications from existing Core state. It never grants
permissions or executes actions by itself.
"""
from datetime import datetime, timezone


def _event_time(item):
    return str(item.get("timestamp") or item.get("started_at") or item.get("created_at") or "")


def build_notifications(*, agent=None, security=None, missions=None, tasks=None, events=None, live=None):
    agent = agent or {}
    security = security or {}
    missions = missions or []
    tasks = tasks or []
    events = events or []
    live = live or {}
    out = []

    if bool(security.get("kill_switch")):
        out.append({"id": "security-kill", "level": "critical", "title": "Kill Switch ativo", "text": "Novas ações estão bloqueadas pelo Permission Manager.", "time": ""})

    pending = int(security.get("pending", 0) or 0)
    if pending:
        out.append({"id": "security-approvals", "level": "warning", "title": f"{pending} aprovação(ões) pendente(s)", "text": "Existem ações aguardando decisão de segurança.", "time": ""})

    if agent and agent.get("ok") and not agent.get("online"):
        out.append({"id": "agent-offline", "level": "warning", "title": "Local Agent offline", "text": "O computador local não está respondendo ao gateway.", "time": ""})

    overdue = [t for t in tasks if t.get("status") != "done" and _is_overdue(t)]
    if overdue:
        out.append({"id": "tasks-overdue", "level": "warning", "title": f"{len(overdue)} tarefa(s) atrasada(s)", "text": "Há tarefas com prazo vencido.", "time": ""})

    failed = [m for m in missions if str(m.get("status", "")).lower() == "failed"]
    if failed:
        latest = failed[-1]
        out.append({"id": "mission-failed", "level": "error", "title": "Missão com falha", "text": str(latest.get("goal") or latest.get("id") or "Uma missão terminou com erro.")[:110], "time": _event_time(latest)})

    current = live.get("current") or {}
    if str(current.get("status", "")).lower() in {"error", "failed", "failure"}:
        out.append({"id": "live-error", "level": "error", "title": "Operação em erro", "text": str(current.get("instruction") or current.get("result") or "A operação atual falhou.")[:110], "time": _event_time(current)})

    recent_errors = []
    for ev in reversed(events[-80:]):
        status = str(ev.get("status") or (ev.get("data") or {}).get("status") or "").lower()
        if status in {"error", "failed", "failure"}:
            recent_errors.append(ev)
            if len(recent_errors) >= 2:
                break
    for idx, ev in enumerate(recent_errors):
        out.append({"id": f"event-error-{idx}-{_event_time(ev)}", "level": "error", "title": "Evento com erro", "text": str(ev.get("event") or "Falha registrada no Core.")[:110], "time": _event_time(ev)})

    # Stable order: critical/errors first, then warnings. Keep the HUD compact.
    rank = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    out.sort(key=lambda x: (rank.get(x.get("level"), 9), x.get("title", "")))
    return out[:8]


def _is_overdue(task):
    due = task.get("due_at")
    if not due:
        return False
    try:
        value = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
        if value.tzinfo is None:
            return value < datetime.now()
        return value < datetime.now(timezone.utc)
    except Exception:
        return False
