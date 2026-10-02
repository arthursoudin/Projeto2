# JARVIS V19.0.0 — Command OS

Camadas V15–V19 sobre a base V14.5.3. Veja `../V19_MANIFEST.md` para o que é executável, o que foi corrigido e o que não foi verificado.

## Uso (aba "Command OS V19")
- **Missões**: criar → "Executar selecionada" ou "Executar próxima da fila" (usa a equipe de agentes; precisa de OpenRouter configurado).
- **Workflows**: salvar ações (allowlist) → escolher dispositivo/grupo → "Executar workflow". Ações destrutivas pedem confirmação e continuam sujeitas ao Permission Manager.
- **Snapshots**: criar / restaurar (confirmação; cria backup pre-restore).
- **Resource Monitor, Diagnóstico, Application Center, busca por Trace ID**.

## Segurança
Nenhum shell arbitrário; o Command OS não contorna Permission Manager nem Kill Switch; o Lab só propõe.
