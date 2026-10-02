"""Jarvis V13.0 — registro seguro de dispositivos.

Nesta versão o módulo é uma fundação para Multi-PC. Ele não abre portas nem
executa comandos: apenas mantém o catálogo de dispositivos autorizados no
armazenamento do Jarvis.
"""
from __future__ import annotations
import secrets
from datetime import datetime, timezone
import store

KEY = "devices"
LIMIT = 50

def _now():
    return datetime.now(timezone.utc).isoformat()

def _rows():
    data = store.load(KEY, [])
    return data[-LIMIT:] if isinstance(data, list) else []

def list_devices():
    return _rows()

def get_device(device_id):
    return next((x for x in _rows() if x.get("id") == device_id), None)

def register(device_id, name=None, capabilities=None, version=None, telemetry=None):
    device_id = str(device_id or "").strip()
    if not device_id or len(device_id) > 120:
        raise ValueError("device_id inválido.")
    rows = _rows()
    item = get_device(device_id)
    if item is None:
        item = {
            "id": device_id,
            "name": str(name or device_id)[:100],
            "created_at": _now(),
            "status": "online",
        }
        rows.append(item)
    item.update({
        "name": str(name or item.get("name") or device_id)[:100],
        "capabilities": list(capabilities or item.get("capabilities") or [])[:30],
        "version": str(version or item.get("version") or "")[:40],
        "status": "online",
        "last_seen": _now(),
    })
    if isinstance(telemetry, dict):
        for key in ("cpu_percent", "ram_em_uso_percent", "ram_total_gb", "ram_livre_gb", "disco_total_gb", "disco_livre_gb", "ligado_ha", "rotinas_ativas", "applications", "application_count"):
            if key in telemetry:
                item[key] = telemetry[key]
    store.save(KEY, rows[-LIMIT:])
    return item

def mark_offline(device_id):
    rows = _rows()
    item = next((x for x in rows if x.get("id") == device_id), None)
    if not item:
        return None
    item["status"] = "offline"
    item["last_seen"] = _now()
    store.save(KEY, rows[-LIMIT:])
    return item

def refresh_status(timeout_seconds=30):
    rows = _rows()
    now_dt = datetime.now(timezone.utc)
    changed = False
    for item in rows:
        raw = item.get("last_seen")
        try:
            seen = datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
            online = bool(seen) and (now_dt - seen).total_seconds() <= timeout_seconds
        except Exception:
            online = False
        new_status = "online" if online else "offline"
        if item.get("status") != new_status:
            item["status"] = new_status
            changed = True
    if changed:
        store.save(KEY, rows[-LIMIT:])
    return rows

def summary():
    rows = refresh_status()
    return {
        "total": len(rows),
        "online": sum(1 for x in rows if x.get("status") == "online"),
        "offline": sum(1 for x in rows if x.get("status") != "online"),
    }
