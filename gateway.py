import hmac
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from jarvis_core import (
    execute_engine,
    save_exchange,
    send_whatsapp_text,
    WA_VERIFY_TOKEN,
    WA_ALLOWED_CONTACTS,
    state,
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
