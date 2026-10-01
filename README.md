# Jarvis Agent V9

V9 integra Honcho ao fluxo real de memória, mantendo memória local como fallback.

## Render — Interface
Build: `pip install -r requirements.txt`
Start: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`

## Render — Gateway
Build: `pip install -r requirements.txt`
Start: `uvicorn gateway:app --host 0.0.0.0 --port $PORT`

## Variáveis
Obrigatória: `OPENROUTER_API_KEY`

Para memória remota: `HONCHO_API_KEY`

Opcionais: `OPENROUTER_MODEL`, `HONCHO_WORKSPACE_ID`, `HONCHO_USER_ID`, `HONCHO_ASSISTANT_ID`, `EDGE_TTS_VOICE`, `EDGE_TTS_RATE`, `EDGE_TTS_PITCH`.

## Memória
A V9 cria peers de usuário/assistente e sessões no Honcho. Recupera contexto antes do OpenRouter e salva o turno depois da resposta. Se Honcho não estiver configurado, a memória local continua funcionando.

## Próximas versões
V10: tarefas + automações.
V11: controle seguro do computador.
V12: WhatsApp real -> Jarvis -> resposta.
V13: permissões e segurança.
