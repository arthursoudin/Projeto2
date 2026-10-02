"""Jarvis V12.2 - voz: microfone (transcrição) e texto limpo para falar.

Transcrição (nesta ordem de preferência, a primeira com chave configurada):
  1. OpenRouter  -> usa a MESMA OPENROUTER_API_KEY do app (endpoint /audio/transcriptions)
  2. Groq        -> GROQ_API_KEY (grátis)
  3. OpenAI      -> OPENAI_API_KEY
Para forçar um deles: STT_PROVIDER=openrouter|groq|openai. Para trocar o modelo: STT_MODEL.
Só usa `requests`.
"""
import base64
import os
import re

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


class VoiceError(Exception):
    """Erro com mensagem já em português, pronta para mostrar ao usuário."""


HINT = ("Comandos para o assistente Jarvis: crie uma pasta, crie um arquivo, abra o VS Code, "
        "abra o navegador, rotina, todo dia às 9h, apague o arquivo, liste os arquivos.")

# Whisper às vezes "alucina" estas frases quando o áudio é só silêncio/ruído.
PHANTOMS = {
    'obrigado', 'obrigada', 'obrigado por assistir', 'legendas pela comunidade amara.org',
    'inscreva-se no canal', 'tchau', 'e aí', 'e ai', '.', '...', 'tá', 'ok',
}


def provider():
    """Qual serviço de transcrição está configurado (ou None)."""
    env = lambda k: os.getenv(k, '').strip()
    base_override = env('STT_BASE_URL').rstrip('/')
    model_override = env('STT_MODEL')
    specs = {
        'openrouter': ('OpenRouter', 'OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1', 'openai/whisper-large-v3', 'json'),
        'groq': ('Groq', 'GROQ_API_KEY', 'https://api.groq.com/openai/v1', 'whisper-large-v3-turbo', 'multipart'),
        'openai': ('OpenAI', 'OPENAI_API_KEY', 'https://api.openai.com/v1', 'whisper-1', 'multipart'),
    }
    forced = env('STT_PROVIDER').lower()
    order = [forced] if forced in specs else ['openrouter', 'groq', 'openai']
    for key in order:
        name, var, base, model, kind = specs[key]
        if env(var):
            return {'id': key, 'name': name, 'key': env(var), 'kind': kind,
                    'url': (base_override or base) + '/audio/transcriptions', 'model': model_override or model}
    return None


def configured():
    return bool(provider() and requests)


def status_text():
    p = provider()
    return f"{p['name']} ({p['model']})" if p else 'não configurada (precisa de OPENROUTER_API_KEY)'


def _audio_format(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'wav'
    return ext if ext in ('wav', 'mp3', 'flac', 'm4a', 'ogg', 'webm', 'aac') else 'wav'


def _post(p, audio_bytes, filename, language, with_hint=True):
    headers = {'Authorization': f"Bearer {p['key']}"}
    if p['kind'] == 'json':   # OpenRouter: JSON com áudio em base64
        body = {'model': p['model'], 'language': language, 'temperature': 0,
                'input_audio': {'data': base64.b64encode(audio_bytes).decode('ascii'), 'format': _audio_format(filename)}}
        if with_hint:         # dica de vocabulário, repassada só ao provedor que a aceitar
            body['provider'] = {'options': {'openai': {'prompt': HINT}, 'groq': {'prompt': HINT}}}
        return requests.post(p['url'], headers=headers, json=body, timeout=45)
    mime = 'audio/wav' if filename.lower().endswith('.wav') else 'application/octet-stream'
    return requests.post(
        p['url'], headers=headers, files={'file': (filename, audio_bytes, mime)},
        data={'model': p['model'], 'language': language, 'response_format': 'json', 'temperature': '0', 'prompt': HINT},
        timeout=45)


def _api_message(r):
    try:
        err = r.json().get('error')
        msg = err.get('message') if isinstance(err, dict) else err
        return str(msg)[:140] if msg else ''
    except Exception:
        return ''


def transcribe(audio_bytes, filename='fala.wav', language='pt'):
    """Áudio (bytes WAV/MP3/WEBM) -> texto. Levanta VoiceError com mensagem amigável."""
    p = provider()
    if not p or not requests:
        raise VoiceError('Microfone não configurado: falta a OPENROUTER_API_KEY no Render.')
    if not audio_bytes or len(audio_bytes) < 1500:
        raise VoiceError('Não ouvi nada. Grave de novo, falando um pouco mais perto do microfone.')
    if len(audio_bytes) > 18 * 1024 * 1024:
        raise VoiceError('Áudio grande demais. Fale um trecho menor.')
    try:
        r = _post(p, audio_bytes, filename, language)
        if p['kind'] == 'json' and r.status_code in (400, 422):   # talvez o provedor rejeitou a dica: tenta sem
            r = _post(p, audio_bytes, filename, language, with_hint=False)
    except requests.Timeout:
        raise VoiceError('A transcrição demorou demais. Tente de novo.')
    except requests.RequestException as e:
        raise VoiceError(f'Não consegui falar com o serviço de transcrição ({type(e).__name__}).')
    code = r.status_code
    if code in (401, 403):
        raise VoiceError(f"A chave do {p['name']} foi recusada. Confira a chave no Render.")
    if code == 402:
        raise VoiceError(f"Sem saldo no {p['name']}. Adicione créditos em openrouter.ai/credits." if p['id'] == 'openrouter'
                         else f"Sem saldo no {p['name']}.")
    if code == 404:
        raise VoiceError(f"Modelo de transcrição não encontrado ({p['model']}). Veja openrouter.ai/models?output_modalities=transcription "
                         "e defina STT_MODEL com o nome completo.")
    if code == 429:
        raise VoiceError('Limite de transcrições atingido por enquanto. Aguarde um pouco ou digite o comando.')
    if code >= 400:
        detalhe = _api_message(r)
        raise VoiceError(f'Erro {code} na transcrição' + (f': {detalhe}' if detalhe else '.'))
    try:
        text = (r.json().get('text') or '').strip()
    except Exception:
        raise VoiceError('Resposta inesperada do serviço de transcrição.')
    if not text or text.lower().strip(' .!') in {x.strip(' .!') for x in PHANTOMS}:
        raise VoiceError('Não entendi o áudio. Pode repetir?')
    return text


_EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d\u2190-\u21FF]')


def clean_for_speech(text, limit=650):
    """Remove markdown, código, links e emojis; corta em fim de frase. Retorna '' se não sobrar nada."""
    t = str(text or '')
    t = re.sub(r'```.*?```', ' ', t, flags=re.S)                    # blocos de código
    t = re.sub(r'`([^`]*)`', r'\1', t)                              # código inline
    t = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', t)                     # imagens
    t = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', t)                  # [texto](url) -> texto
    t = re.sub(r'https?://\S+', 'link', t)
    t = re.sub(r'^\s{0,3}#{1,6}\s*', '', t, flags=re.M)             # títulos
    t = re.sub(r'^\s*[-*+•]\s+', '', t, flags=re.M)                 # marcadores
    t = re.sub(r'^\s*\d+[.)]\s+', '', t, flags=re.M)                # listas numeradas
    t = re.sub(r'^\s*>\s?', '', t, flags=re.M)                      # citações
    t = re.sub(r'\|', ' ', t)                                       # tabelas
    t = re.sub(r'[*_~]{1,3}', '', t)                                # negrito/itálico
    t = _EMOJI.sub('', t)
    t = re.sub(r'\b(?:em|no|na|de|do|da)\s+[A-Za-z]:\\\S*[^\s.,;:!?)]', 'no caminho informado', t)   # "em C:\\..."
    t = re.sub(r'[A-Za-z]:\\\S*[^\s.,;:!?)]', 'o caminho informado', t)                              # caminhos soltos
    t = re.sub(r'\s*\n+\s*', '. ', t)
    t = re.sub(r'\.\s*\.', '.', t)
    t = re.sub(r'([!?])\s*\.', r'\1', t)
    t = re.sub(r'\s{2,}', ' ', t).strip(' .')
    if not t:
        return ''
    if len(t) > limit:
        cut = t[:limit]
        end = max(cut.rfind('. '), cut.rfind('? '), cut.rfind('! '))
        t = (cut[:end + 1] if end > limit * 0.5 else cut.rsplit(' ', 1)[0]) + ' O restante está na tela.'
    return t
