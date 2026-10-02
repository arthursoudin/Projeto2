# Jarvis V11 — Local Agent + Controle Seguro do PC

A V11 mantém a interface/IA/memória/tarefas da V10 e adiciona um agente local para executar apenas ações explicitamente permitidas no Windows.

## Arquitetura

Render: Jarvis + OpenRouter + Honcho + tarefas + gateway.
PC: `local_agent/agent.py` faz polling no gateway e executa somente `open_app` e `create_folder`.

## Render

### projeto2-1 (Interface)
Mantenha `OPENROUTER_API_KEY` e `HONCHO_API_KEY`.
Adicione:
- `JARVIS_GATEWAY_URL` = URL pública do projeto2-2
- `LOCAL_AGENT_TOKEN` = um token secreto escolhido por você

### projeto2-2 (Gateway)
Adicione a mesma variável:
- `LOCAL_AGENT_TOKEN` = exatamente o mesmo token usado no projeto2-1

Start command do gateway:
`uvicorn gateway:app --host 0.0.0.0 --port $PORT`

## PC Windows — sem administrador

1. Abra `local_agent/setup_agent.bat`.
2. Informe a URL do gateway.
3. Informe o mesmo `LOCAL_AGENT_TOKEN` do Render.
4. Execute `start_agent.bat`.

O agente não instala serviço de administrador. Ele roda como usuário normal.

## Ações V11

- Abrir VS Code
- Abrir Bloco de Notas
- Abrir Calculadora
- Abrir navegador
- Criar pasta dentro de `%USERPROFILE%\\Jarvis`

A lista é propositalmente pequena nesta primeira versão. Não há shell remoto genérico.


## V11.2 — Controle local expandido
Além de abrir aplicativos e criar pastas, o agente local permite abrir pastas/arquivos somente dentro de `~/Jarvis`, criar arquivos nesse espaço e consultar informações básicas do computador. Não existe execução arbitrária de shell.


V11.2: o Gateway aguarda o resultado real do Local Agent antes de entregar a resposta ao modelo.
