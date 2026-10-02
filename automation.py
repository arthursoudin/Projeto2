"""V12.4 — regras de automação persistentes. A execução pode ser acionada pelo scheduler do host."""
from datetime import datetime, timezone
from pathlib import Path
import json, uuid

AUTOMATIONS_FILE = Path('.jarvis_automations.json')

def _load():
    try:
        return json.loads(AUTOMATIONS_FILE.read_text(encoding='utf-8')) if AUTOMATIONS_FILE.exists() else []
    except Exception:
        return []

def _save(items):
    AUTOMATIONS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')

def create_automation(name, schedule, action, enabled=True):
    items = _load()
    item = {'id': uuid.uuid4().hex[:12], 'name': name, 'schedule': schedule, 'action': action,
            'enabled': bool(enabled), 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    items.append(item); _save(items); return item

def list_automations(): return _load()

def set_enabled(automation_id, enabled):
    items = _load()
    for item in items:
        if item.get('id') == automation_id:
            item['enabled'] = bool(enabled); _save(items); return item
    return None
