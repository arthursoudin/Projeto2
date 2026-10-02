"""Jarvis V14.5.3 Quality Gate.
Run: python quality_gate.py
This deliberately tests several layers without contacting OpenRouter or requiring Streamlit.
"""
from __future__ import annotations
import ast, pathlib, re, sys, time, tempfile, importlib
ROOT=pathlib.Path(__file__).resolve().parent
errors=[]; checks=0

def check(name, fn):
    global checks
    checks += 1
    try:
        ok=bool(fn())
        if not ok: raise AssertionError('returned False')
        print(f'PASS | {name}')
    except Exception as e:
        errors.append((name,e)); print(f'FAIL | {name} | {type(e).__name__}: {e}')

def text(path): return (ROOT/path).read_text(encoding='utf-8')

# 1) syntax / importable pure modules
for rel in ['app.py','gateway.py','pc_control.py','security.py','devices.py','orchestrator.py','computer_agent.py','local_agent/agent.py']:
    check(f'AST {rel}', lambda rel=rel: ast.parse(text(rel)) is not None)

sys.path.insert(0,str(ROOT))
import pc_control

# 2) parser matrix: accents, aliases, app names, file/folder commands
cases={
    'abra o chrome':('open_app','chrome'),
    'abra chrome':('open_app','chrome'),
    'abra o VS Code':('open_app','vscode'),
    'abra o DBeaver':('open_app','dbeaver'),
    'abra o explorador de arquivos':('open_app','explorer'),
    'mostre as informações do meu PC':('system_info',None),
    'mostre as informacoes do computador':('system_info',None),
    'crie uma pasta chamada TesteJarvis':('create_folder','TesteJarvis'),
    'crie um arquivo teste.txt':('create_file','teste.txt'),
    'abra o site github.com':('open_url','github.com'),
}
for prompt, expected in cases.items():
    def f(prompt=prompt,expected=expected):
        got=pc_control.parse_pc_commands(prompt)
        assert got, got
        action,params=got[0]
        assert action==expected[0], (got,expected)
        if expected[1] is not None:
            assert expected[1].lower() in str(params).lower(), (got,expected)
        return True
    check(f'Parser: {prompt}', f)

# 3) negative routing: ordinary conversation must not become PC command
for prompt in ['olá jarvis','como funciona python?','me explique o que é SQL','quero estudar matemática']:
    check(f'Negative parser: {prompt}', lambda prompt=prompt: pc_control.parse_pc_commands(prompt)==[])

# 4) source-level fast path guarantees
app=text('app.py')
check('unicodedata import exists', lambda: 'import os, json, asyncio, datetime as dt, uuid, re, base64, unicodedata, time' in app)
check('No unicodeode typo', lambda: 'unicodeode' not in app)
check('PC parser before LLM', lambda: app.index('steps=parse_pc_commands(prompt)') < app.index('ask_llm(prompt,result,context)'))
check('Fast PC response bypasses LLM', lambda: "elif tool == 'computer':" in app and 'format_pc_fast(result)' in app)
check('Device query fast path exists', lambda: 'is_devices_intent' in app and 'connected_devices_fast' in app)
check('Build fingerprint exists', lambda: '14.5.3-command-reliability' in text('gateway.py') and "APP_VERSION=os.getenv('JARVIS_APP_VERSION','14.5.3')" in app)

# 5) version consistency
for rel in ['gateway.py','local_agent/agent.py','orchestrator.py']:
    check(f'Version 14.5.3 in {rel}', lambda rel=rel: '14.5.3' in text(rel))

# 6) security invariants
sec=text('security.py'); gw=text('gateway.py')
check('Delete remains high risk', lambda: "'delete_path':'high'" in sec)
check('Kill switch exists', lambda: "'kill_switch'" in sec and 'kill_switch' in gw)
check('Arbitrary shell absent from PC actions', lambda: 'shell=True' not in text('pc_control.py') and 'subprocess.call' not in text('pc_control.py'))
check('Allowed action list exists', lambda: 'ALLOWED_ACTIONS=' in gw and 'open_app' in gw)


# 8) Local-agent integration invariants: the UI parser and PC agent must agree on Chrome.
agent=text('local_agent/agent.py')
check('Chrome is allowed by Local Agent', lambda: '"chrome": {"label": "Google Chrome"' in agent and 'open_app' in agent)
check('Local Agent reports current build', lambda: 'VERSION = "14.5.3"' in agent)
check('Chrome lookup uses known install locations', lambda: 'Google\\Chrome\\Application' in agent or 'Google/Chrome/Application' in agent)
check('Fast device route uses live agent status', lambda: 'agent/status' in app and "live_agent" in app)
check('No generic LLM fallback for computer result', lambda: "elif tool == 'computer':" in app and 'format_pc_fast(result)' in app)

# 7) repeat parser stress loop
stress=['abra chrome','abra o chrome','abrir chrome','abre chrome','abra o VS Code','mostre as informações do meu PC','crie uma pasta chamada TesteJarvis']*100
start=time.perf_counter()
for prompt in stress:
    pc_control.parse_pc_commands(prompt)
elapsed=time.perf_counter()-start
check(f'Parser stress {len(stress)} commands under 0.50s', lambda: elapsed < 0.50)
print(f'\nQUALITY GATE: {checks-len(errors)}/{checks} checks passed')
if errors:
    print('\nFailures:')
    for name,e in errors: print(f'- {name}: {e}')
    raise SystemExit(1)
print('RESULT: PASS')
