# Jarvis Agent V6

V6 adiciona pesquisa e leitura web controladas ao motor multiagente.

## Novidades
- `web_search`: pesquisa web pública via DuckDuckGo HTML.
- `web_open`: abre páginas públicas HTTP/HTTPS e extrai texto principal.
- Proteção básica contra localhost e IPs privados/reservados.
- Tools web disponíveis para os agentes por permissão.
- Aba `🌐 Web` para testes manuais.

## Render
Root Directory: `Jarvis_Agent_v6`
Build: `pip install -r requirements.txt`
Start: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`

Mantenha as variáveis existentes `OPENROUTER_API_KEY`, `HONCHO_API_KEY` e `HONCHO_WORKSPACE_ID`.
