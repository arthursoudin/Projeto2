"""Jarvis V12.1 - WhatsApp (Meta WhatsApp Cloud API).

Lógica do canal, sem FastAPI (as rotas ficam no gateway.py). Só usa `requests`.

Variáveis de ambiente (serviço do GATEWAY no Render):
  WHATSAPP_TOKEN            token de acesso da Meta (use um token permanente de "usuário do sistema")
  WHATSAPP_PHONE_NUMBER_ID  ID do número do WhatsApp Business (não é o telefone)
  WHATSAPP_VERIFY_TOKEN     texto que você inventa; a Meta o devolve ao validar o webhook
  WHATSAPP_APP_SECRET       "Chave secreta do app" (Configurações do app > Básico); valida a assinatura
  WHATSAPP_ALLOWED_NUMBERS  seu número com DDI, ex.: 5511999998888 (vários: separe por vírgula)

Segurança: o Jarvis controla o PC, então só responde a números da lista e só aceita
mensagens com assinatura válida da Meta. Sem WHATSAPP_APP_SECRET ele recusa tudo.
"""
import hashlib
import hmac
import os
import re
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

GRAPH_VERSION = os.getenv('WHATSAPP_GRAPH_VERSION', 'v21.0').strip() or 'v21.0'
MAX_TEXT = 3800                 # o limite da Meta é 4096 por mensagem
MAX_MEDIA = 16 * 1024 * 1024
REQUIRED = ['WHATSAPP_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_VERIFY_TOKEN',
            'WHATSAPP_APP_SECRET', 'WHATSAPP_ALLOWED_NUMBERS']

_lock = threading.Lock()
_seen = OrderedDict()           # ids de mensagens já tratadas (a Meta reenvia se demorarmos)
_hits = {}                      # número -> instantes das últimas mensagens (limite de ritmo)
LOG = deque(maxlen=30)          # atividade recente (sem o conteúdo das mensagens)
STATE = {'last_message_at': '', 'day': '', 'today': 0, 'last_error': ''}

ERROR_HINTS = {
    190: 'Token do WhatsApp inválido ou expirado. Gere um token permanente e atualize WHATSAPP_TOKEN.',
    131030: 'Esse número não está na lista de destinatários permitidos da Meta (modo de teste).',
    131047: 'Passou de 24h desde a sua última mensagem; mande um "oi" para reabrir a conversa.',
    131056: 'Muitas mensagens em pouco tempo; aguarde um pouco.',
}


def _env(name):
    return os.getenv(name, '').strip()


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.getenv('JARVIS_TZ', 'America/Sao_Paulo'))
    except Exception:
        return timezone(timedelta(hours=-3))


def _now():
    return datetime.now(_tz())


# ------------------------------------------------------------------ configuração
def missing():
    return [k for k in REQUIRED if not _env(k)]


def configured():
    return bool(requests) and not missing()


def _digits(n):
    return re.sub(r'\D', '', str(n or ''))


def _variants(n):
    """O WhatsApp às vezes entrega números do Brasil sem o 9 extra. Aceita as duas formas."""
    n = _digits(n)
    out = {n} if n else set()
    if n.startswith('55'):
        if len(n) == 13 and n[4] == '9':
            out.add(n[:4] + n[5:])
        elif len(n) == 12 and n[4] in '6789':
            out.add(n[:4] + '9' + n[4:])
    return out


def allowed_numbers():
    out = set()
    for part in re.split(r'[,;\n]+', _env('WHATSAPP_ALLOWED_NUMBERS')):
        out |= _variants(part)
    return out


def is_allowed(number):
    return bool(_variants(number) & allowed_numbers())


def mask(number):
    d = _digits(number)
    return '***' + d[-4:] if d else '?'


# ------------------------------------------------------------------ webhook
def verify_challenge(mode, token, challenge):
    """GET de validação da Meta. Devolve o texto do desafio, ou None se for recusado."""
    expected = _env('WHATSAPP_VERIFY_TOKEN')
    if mode == 'subscribe' and expected and hmac.compare_digest(str(token or ''), expected):
        return str(challenge or '')
    return None


def valid_signature(raw_body, header):
    """Confere o X-Hub-Signature-256. Sem WHATSAPP_APP_SECRET, recusa (nunca aceita sem assinatura)."""
    secret = _env('WHATSAPP_APP_SECRET')
    if not secret or not header or not str(header).startswith('sha256='):
        return False
    digest = hmac.new(secret.encode('utf-8'), raw_body or b'', hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, str(header)[7:])


def extract_messages(payload):
    """Payload da Meta -> lista de {'id','from','type','text','media_id'} (ignora recibos de entrega)."""
    out = []
    try:
        for entry in payload.get('entry') or []:
            for change in entry.get('changes') or []:
                for m in (change.get('value') or {}).get('messages') or []:
                    kind = m.get('type') or ''
                    item = {'id': m.get('id') or '', 'from': m.get('from') or '', 'type': kind, 'text': '', 'media_id': ''}
                    if kind == 'text':
                        item['text'] = (m.get('text') or {}).get('body') or ''
                    elif kind == 'audio':
                        item['media_id'] = (m.get('audio') or {}).get('id') or ''
                    if item['id'] and item['from']:
                        out.append(item)
    except Exception:
        return []
    return out


def already_seen(message_id):
    with _lock:
        if message_id in _seen:
            return True
        _seen[message_id] = time.time()
        while len(_seen) > 500:
            _seen.popitem(last=False)
    return False


def rate_ok(number, limit=20, window=60):
    """No máximo `limit` mensagens por `window` segundos por número."""
    now = time.time()
    with _lock:
        q = _hits.setdefault(_digits(number), deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
    return True


# ------------------------------------------------------------------ atividade
def log_event(direction, number, kind, ok=True, note=''):
    """Registra atividade para o dashboard (só tipo e resultado; o texto das mensagens não é guardado)."""
    now = _now()
    with _lock:
        LOG.appendleft({'quando': now.strftime('%d/%m %H:%M:%S'), 'sentido': 'recebida' if direction == 'in' else 'enviada',
                        'numero': mask(number), 'tipo': kind, 'ok': bool(ok), 'nota': str(note)[:80]})
        if direction == 'in' and ok:
            day = now.strftime('%Y-%m-%d')
            if STATE['day'] != day:
                STATE['day'], STATE['today'] = day, 0
            STATE['today'] += 1
            STATE['last_message_at'] = now.strftime('%d/%m %H:%M')


def _set_error(msg):
    with _lock:
        STATE['last_error'] = str(msg)[:200]


def status():
    day = _now().strftime('%Y-%m-%d')
    with _lock:
        today = STATE['today'] if STATE['day'] == day else 0
        n_allowed = len([x for x in re.split(r'[,;\n]+', _env('WHATSAPP_ALLOWED_NUMBERS')) if _digits(x)])
        return {'configured': configured(), 'missing': missing(), 'allowed_count': n_allowed,
                'last_message_at': STATE['last_message_at'], 'messages_today': today,
                'last_error': STATE['last_error'], 'log': list(LOG)[:10]}


# ------------------------------------------------------------------ envio / mídia
def _api(path):
    return f'https://graph.facebook.com/{GRAPH_VERSION}/{path}'


def _auth():
    return {'Authorization': f"Bearer {_env('WHATSAPP_TOKEN')}"}


def _api_error(r):
    try:
        err = (r.json() or {}).get('error') or {}
        code = err.get('code')
        return ERROR_HINTS.get(code) or str(err.get('message') or f'HTTP {r.status_code}')[:160]
    except Exception:
        return f'HTTP {r.status_code}'


def split_text(body, size=MAX_TEXT):
    """Quebra textos longos em pedaços, preferindo quebras de linha/espaço."""
    body = str(body or '').strip()
    if not body:
        return []
    parts = []
    while len(body) > size:
        cut = max(body.rfind('\n', 0, size), body.rfind(' ', 0, size))
        if cut < size * 0.5:
            cut = size
        parts.append(body[:cut].rstrip())
        body = body[cut:].lstrip()
    if body:
        parts.append(body)
    return parts


def send_text(to, body):
    """Envia texto. Retorna (ok, erro)."""
    if not configured():
        return False, 'WhatsApp não configurado.'
    ok_all, err = True, ''
    for part in split_text(body):
        try:
            r = requests.post(_api(f"{_env('WHATSAPP_PHONE_NUMBER_ID')}/messages"), headers=_auth(), timeout=15,
                              json={'messaging_product': 'whatsapp', 'to': _digits(to), 'type': 'text',
                                    'text': {'body': part, 'preview_url': False}})
        except Exception as e:
            ok_all, err = False, f'{type(e).__name__} ao enviar'
            break
        if r.status_code >= 400:
            ok_all, err = False, _api_error(r)
            break
    log_event('out', to, 'texto', ok_all, err)
    if not ok_all:
        _set_error(err)
    return ok_all, err


def mark_read(message_id):
    """Marca como lida (melhor esforço; falhar aqui não importa)."""
    if not configured() or not message_id:
        return
    try:
        requests.post(_api(f"{_env('WHATSAPP_PHONE_NUMBER_ID')}/messages"), headers=_auth(), timeout=8,
                      json={'messaging_product': 'whatsapp', 'status': 'read', 'message_id': message_id})
    except Exception:
        pass


def download_media(media_id):
    """Baixa um áudio recebido. Retorna (bytes, mime). Levanta RuntimeError com mensagem amigável."""
    if not configured():
        raise RuntimeError('WhatsApp não configurado.')
    try:
        r = requests.get(_api(str(media_id)), headers=_auth(), timeout=15)
        if r.status_code >= 400:
            raise RuntimeError(_api_error(r))
        meta = r.json()
        url, mime = meta.get('url'), meta.get('mime_type') or 'audio/ogg'
        if not url:
            raise RuntimeError('A Meta não devolveu o link do áudio.')
        if int(meta.get('file_size') or 0) > MAX_MEDIA:
            raise RuntimeError('Áudio grande demais. Mande um trecho menor.')
        rr = requests.get(url, headers=_auth(), timeout=30)
        if rr.status_code >= 400:
            raise RuntimeError(_api_error(rr))
        if len(rr.content) > MAX_MEDIA:
            raise RuntimeError('Áudio grande demais. Mande um trecho menor.')
        return rr.content, mime
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f'Não consegui baixar o áudio ({type(e).__name__}).')


def audio_filename(mime):
    m = str(mime or '').lower()
    for key, ext in (('ogg', 'ogg'), ('opus', 'ogg'), ('mpeg', 'mp3'), ('mp3', 'mp3'), ('mp4', 'm4a'),
                     ('m4a', 'm4a'), ('aac', 'aac'), ('amr', 'ogg'), ('wav', 'wav'), ('webm', 'webm')):
        if key in m:
            return f'voz.{ext}'
    return 'voz.ogg'
