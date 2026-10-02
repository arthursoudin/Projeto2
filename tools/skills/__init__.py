"""Catálogo de Skills do Jarvis V12.7.

As skills são descritas em skills/catalog.json para que o catálogo possa
ser ampliado sem alterar o núcleo do Jarvis.
"""
import json
from pathlib import Path

def load_catalog(path=None):
    path = Path(path) if path else Path(__file__).with_name("catalog.json")
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}
