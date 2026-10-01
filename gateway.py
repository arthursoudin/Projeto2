import hmac
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, Response, JSONResponse
import requests

from jarvis_core import (
    execute_engine,
    save_exchange,
    send_whatsapp_text,
    WA_VERIFY_TOKEN,
    WA_ALLOWED_CONTACTS,
    state,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_MODEL_ID,
)

app = FastAPI(title="Jarvis Gateway V7.1", version="7.1")


def allowed(identifier, allowlist):
    return not allowlist or str(identifier) in allowlist


def whatsapp_event(payload):
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        messages = value.get("messages", [])
        for msg in messages:
            if msg.get("type") != "text":
                continue
            sender = msg.get("from", "")
            body = msg.get("text", {}).get("body", "")
            if not allowed(sender, WA_ALLOWED_CONTACTS):
                continue
            answer = execute_engine(body, state.agents)["final"]
            save_exchange(f"[WhatsApp:{sender}] {body}", answer)
            send_whatsapp_text(sender, answer)
        return {"ok": True}
    except (KeyError, IndexError, TypeError):
        return {"ok": True, "ignored": "payload sem mensagem de texto"}


@app.get("/health")
async def health():
    return {"ok": True, "service": "jarvis-gateway", "version": "7.1", "channels": ["whatsapp"]}


@app.get("/test-voice")
async def test_voice():
    """Gera um áudio curto para validar a configuração do ElevenLabs."""
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "ElevenLabs não configurado",
                "required": ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"],
            },
        )

    text = "Olá. Este é um teste de voz do Jarvis. Se você está ouvindo isso, o ElevenLabs está funcionando."
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}?output_format=mp3_44100_128"
    try:
        r = requests.post(
            url,
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": text, "model_id": ELEVENLABS_MODEL_ID},
            timeout=60,
        )
        if not r.ok:
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "error": "ElevenLabs recusou a solicitação",
                    "status": r.status_code,
                    "details": r.text[:500],
                },
            )
        return Response(
            content=r.content,
            media_type="audio/mpeg",
            headers={"Content-Disposition": 'inline; filename="jarvis-test.mp3"'},
        )
    except requests.RequestException as exc:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@app.get("/webhook/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(request: Request):
    p = request.query_params
    mode = p.get("hub.mode")
    token = p.get("hub.verify_token")
    challenge = p.get("hub.challenge", "")
    if mode == "subscribe" and WA_VERIFY_TOKEN and hmac.compare_digest(token or "", WA_VERIFY_TOKEN):
        return challenge
    raise HTTPException(status_code=403, detail="Falha na verificação do webhook")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    try:
        return whatsapp_event(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
