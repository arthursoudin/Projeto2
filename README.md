# Jarvis Agent V7.1 — WhatsApp + ElevenLabs

V7.1 mantém o núcleo do Jarvis da V7 e remove Telegram e Slack.

## Incluído
- Interface Streamlit
- OpenRouter como cérebro
- Honcho para memória
- Multiagentes, Skills e Tools
- Pesquisa/abertura de páginas públicas
- WhatsApp Cloud API
- ElevenLabs para voz, com Edge TTS como fallback
- Gateway FastAPI separado para o webhook do WhatsApp

## Não incluído
- Telegram
- Slack

## Render — Interface
Root Directory: `Jarvis_Agent_v7_1`

Build Command:
```text
pip install -r requirements.txt
```

Start Command:
```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

## Render — Gateway
Crie um segundo Web Service apontando para a mesma pasta.

Build Command:
```text
pip install -r requirements.txt
```

Start Command:
```text
uvicorn gateway:app --host 0.0.0.0 --port $PORT
```

## Variáveis de ambiente
Obrigatórias para o núcleo:
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL` (opcional)
- `HONCHO_API_KEY`
- `HONCHO_WORKSPACE_ID`

WhatsApp:
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_API_VERSION` (opcional)
- `WHATSAPP_ALLOWED_CONTACTS` (opcional, CSV; vazio = não filtra)

ElevenLabs:
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_MODEL_ID` (opcional)

## Endpoints
```text
GET  /health
GET  /webhook/whatsapp
POST /webhook/whatsapp
```

## Segurança
Nunca coloque tokens ou chaves no código ou no GitHub. Use Environment Variables do Render.
