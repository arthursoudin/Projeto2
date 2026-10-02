"""Jarvis V12.4 - armazenamento persistente.

Com SUPABASE_URL + SUPABASE_KEY configurados, guarda tudo no Supabase (tabela jarvis_kv)
e os dados sobrevivem a reinícios do Render. Sem isso, usa arquivos locais (temporários no Render).
Só usa `requests`, sem dependências novas.
"""
import json
import os
from pathlib import Path

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

TABLE = 'jarvis_kv'
_last_error = {'msg': ''}


def _url():
    return os.getenv('SUPABASE_URL', '').strip().rstrip('/')


def _key():
    return os.getenv('SUPABASE_KEY', '').strip()


def enabled():
    return bool(_url() and _key() and requests)


def backend():
    return 'supabase' if enabled() else 'arquivo'


def _headers(extra=None):
    key = _key()
    h = {'apikey': key, 'Content-Type': 'application/json'}
    # Chaves novas (sb_secret_...) NÃO são JWT: vão só no cabeçalho apikey.
    # Chaves legadas (JWT, começam com "eyJ") também aceitam Authorization.
    if key.startswith('eyJ'):
        h['Authorization'] = f'Bearer {key}'
    h.update(extra or {})
    return h


def _endpoint():
    return f'{_url()}/rest/v1/{TABLE}'


def _file(key):
    base = os.getenv('JARVIS_STORE_DIR', '').strip()
    if base:
        Path(base).mkdir(parents=True, exist_ok=True)
        return Path(base) / f'.jarvis_{key}.json'
    return Path(f'.jarvis_{key}.json')


def _file_load(key, default):
    try:
        p = _file(key)
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
    except Exception:
        return default


def _file_save(key, data):
    try:
        _file(key).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def _remote_get(key):
    """Retorna (existe, valor). Levanta exceção se der erro de rede/HTTP."""
    r = requests.get(_endpoint(), headers=_headers(), params={'key': f'eq.{key}', 'select': 'value'}, timeout=8)
    r.raise_for_status()
    rows = r.json()
    return (True, rows[0]['value']) if rows else (False, None)


def _remote_set(key, data):
    r = requests.post(
        _endpoint(), params={'on_conflict': 'key'},
        headers=_headers({'Prefer': 'resolution=merge-duplicates,return=minimal'}),
        data=json.dumps({'key': key, 'value': data}, ensure_ascii=False).encode('utf-8'), timeout=8)
    r.raise_for_status()


def load(key, default):
    """Lê uma chave. No Supabase; se estiver vazio mas existir arquivo local, migra o arquivo para lá."""
    if enabled():
        try:
            exists, value = _remote_get(key)
            _last_error['msg'] = ''
            if exists:
                return value
            local = _file_load(key, None)
            if local not in (None, [], {}):
                save(key, local)
                return local
            return default
        except Exception as e:
            _last_error['msg'] = f'{type(e).__name__}: {e}'[:200]
    return _file_load(key, default)


def save(key, data):
    """Grava uma chave (e mantém uma cópia local como reserva)."""
    ok_local = _file_save(key, data)
    if enabled():
        try:
            _remote_set(key, data)
            _last_error['msg'] = ''
            return True
        except Exception as e:
            _last_error['msg'] = f'{type(e).__name__}: {e}'[:200]
            return False
    return ok_local


def status():
    """Para exibir na interface: {'backend', 'ok', 'detalhe'}."""
    if not enabled():
        return {'backend': 'arquivo', 'ok': True,
                'detalhe': 'Temporário: os dados somem quando o Render reinicia. Configure SUPABASE_URL e SUPABASE_KEY.'}
    try:
        _remote_get('__ping__')
        return {'backend': 'supabase', 'ok': True, 'detalhe': 'Supabase conectado.'}
    except Exception as e:
        msg = str(e)
        dica = ''
        if '404' in msg or 'PGRST205' in msg:
            dica = ' A tabela jarvis_kv não existe: rode o SQL do README no Supabase.'
        elif '401' in msg or '403' in msg:
            dica = ' Chave recusada: confira SUPABASE_KEY.'
        return {'backend': 'supabase', 'ok': False, 'detalhe': f'Falha: {type(e).__name__}.{dica}'}
