# V14.5.2 — Quality Gate

Antes do deploy, execute `python quality_gate.py` ou `run_quality_gate.bat`.

O gate verifica: sintaxe, parser de comandos, acentos, aliases de aplicativos, comandos negativos, ordem do roteamento rápido, ausência do typo `unicodeode`, bypass do LLM para ações do PC, consulta rápida de dispositivos, versões, invariantes de segurança e 700 chamadas de estresse do parser.

## Diagnóstico de deploy

Após publicar, a aba **Sistema** deve mostrar `14.5.2` e `Build: 14.5.2-quality-gate`. O gateway `/health` deve retornar `version: 14.5.2` e `build: 14.5.2-quality-gate`. Se esses valores não aparecerem, o serviço não está executando o commit esperado.
