# V19 Quality Gate

Rodar:
- `python quality_gate.py`  → esperado **52/52 PASS**
- `python -m pytest -q tests/test_v19_command_os.py`  → esperado **20/20** (ou `python -m unittest` nos legados)
- `python -m py_compile app.py gateway.py orchestrator.py local_agent/agent.py v19_command_os.py`

As checagens 9) do gate executam o código V19 (workflow, missão, restore, recursos, lab) em um store temporário.
Os testes legados foram atualizados para a política de segurança atual (aprovação para risco médio, `delete_path` bloqueado por padrão).
