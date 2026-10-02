"""Jarvis V13.3 — Live Operations.

Camada de observabilidade derivada da timeline persistente. Não executa ações
e não cria permissões. Identifica operações em andamento, duração, agente,
ação e resultado a partir dos eventos registrados pelo Core.
"""
from __future__ import annotations
from datetime import datetime, timezone
import orchestrator

START_EVENTS = {"planner_started", "agent_started"}
END_EVENTS = {"planner_completed", "planner_finished", "agent_completed", "agent_skipped"}

def _dt(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None

def _duration_ms(start, end=None):
    if start is None:
        return None
    if end is not None:
        return round(max(0.0, (end-start).total_seconds()*1000), 1)
    return round(max(0.0, (datetime.now(timezone.utc)-start).total_seconds()*1000), 1)

def snapshot(limit=12):
    events=orchestrator.events()
    open_ops={}
    completed=[]
    for ev in events:
        data=ev.get("data") if isinstance(ev.get("data"),dict) else {}
        op=data.get("operation_id")
        if not op:
            continue
        kind=ev.get("event")
        if kind in START_EVENTS:
            open_ops[op]={"operation_id":op,"started_at":ev.get("timestamp"),"start_dt":_dt(ev.get("timestamp")),
                          "type":kind.replace("_started","").upper(),"agent":data.get("agent") or "Planner",
                          "mission_id":data.get("mission_id"),"instruction":str(data.get("instruction") or data.get("goal") or "")[:500],
                          "status":"running"}
        elif kind in END_EVENTS and op in open_ops:
            item=open_ops.pop(op)
            end_dt=_dt(ev.get("timestamp"))
            ok=data.get("ok",True)
            item.update({"status":"success" if ev.get("status") in ("success","info") and ok is not False else "error",
                         "ended_at":ev.get("timestamp"),"duration_ms":data.get("duration_ms") or _duration_ms(item.get("start_dt"),end_dt),
                         "result":str(data.get("result") or data.get("instruction") or "")[:700],
                         "end_event":kind})
            item.pop("start_dt",None)
            completed.append(item)
    running=list(open_ops.values())
    for item in running:
        item["duration_ms"]=_duration_ms(item.get("start_dt"))
        item.pop("start_dt",None)
    recent=(completed+running)[-limit:]
    recent.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    current=running[-1] if running else (recent[0] if recent and recent[0].get("status") in ("success","error") else None)
    return {"ok":True,"version":"13.3.0","current":current,"running":running,"recent":recent[:limit],"event_count":len(events),"server_time":datetime.now(timezone.utc).isoformat()}

def compact_events(limit=20):
    rows=[]
    for ev in reversed(orchestrator.events()[-limit:]):
        data=ev.get("data") if isinstance(ev.get("data"),dict) else {}
        rows.append({"time":str(ev.get("timestamp", ""))[11:19],"event":ev.get("event",""),"status":ev.get("status",""),
                     "agent":data.get("agent") or "Planner","action":data.get("instruction") or data.get("result") or data.get("goal") or ""})
    return rows
