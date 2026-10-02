# Laboratório Noturno do Jarvis

O `overnight_agents.py` roda ciclos de avaliação contínua e gera relatórios em `overnight_workspace/reports/`.

Agentes: Qualidade, Exemplos Web, Segurança, Red Team defensivo, Testes e Melhorias.

O Red Team cria apenas cenários hipotéticos e seguros. Não executa ataques reais.

Por padrão o laboratório não altera a produção. Ele testa, pesquisa, avalia e cria backlog/propostas para revisão no dia seguinte.

Para deixar rodando no Windows: `start_overnight_loop.bat`.

Variáveis opcionais:
- `JARVIS_NIGHT_INTERVAL_MINUTES` — intervalo entre ciclos (padrão 30)
- `JARVIS_NIGHT_MAX_CYCLES` — 0 = sem limite
- `OPENROUTER_API_KEY` — necessária para avaliações LLM
