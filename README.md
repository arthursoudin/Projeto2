# Jarvis V10 — Render

V10 evolui a V9 com um gerenciador de tarefas e uma base de automações.

## Mantido da V9
- OpenRouter
- Honcho Memory
- Memória local de fallback
- Skills
- Tools
- Web search
- Edge TTS
- Gateway FastAPI

## Novo na V10
- tarefas com ID
- status pendente/concluída
- prioridade
- prazo/data e hora
- tarefas atrasadas
- recorrência simples (diária e semanal)
- conclusão/exclusão por comando
- painel de tarefas
- painel de automações
- endpoint `/tasks` no gateway

## Render — Interface (`projeto2-1`)
Runtime: Python 3
Build:
`pip install -r requirements.txt`

Start:
`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`

Variáveis obrigatórias:
- `OPENROUTER_API_KEY`
- `HONCHO_API_KEY`

Opcionais:
- `OPENROUTER_MODEL` (padrão: `openai/gpt-oss-120b`)
- `HONCHO_WORKSPACE_ID` (padrão: `jarvis`)
- `HONCHO_USER_ID` (padrão: `user`)
- `HONCHO_ASSISTANT_ID` (padrão: `jarvis`)
- `EDGE_TTS_VOICE`
- `EDGE_TTS_RATE`
- `EDGE_TTS_PITCH`

## Render — Gateway (`projeto2-2`)
Build:
`pip install -r requirements.txt`

Start:
`uvicorn gateway:app --host 0.0.0.0 --port $PORT`

## Observação sobre automações
A V10 registra regras, prazos e recorrências e verifica o estado quando a aplicação é acessada. Um processo contínuo de lembretes em background não é tratado como garantido em um serviço web comum do Render. A V11/V12 poderá conectar um scheduler externo ou gateway dedicado para execução confiável.

## Python
`.python-version` = 3.13.5
