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

def register(device_id, name=None, capabilities=None, version=None):
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
        "capabilities": list(capabilities or [])[:30],
        "version": str(version or "")[:40],
        "status": "online",
        "last_seen": _now(),
    })
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

def summary():
    rows = _rows()
    return {
        "total": len(rows),
        "online": sum(1 for x in rows if x.get("status") == "online"),
        "offline": sum(1 for x in rows if x.get("status") != "online"),
    }
