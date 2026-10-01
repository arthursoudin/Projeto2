import json, os, time, subprocess, pathlib, requests, webbrowser, sys

CONFIG=pathlib.Path(__file__).with_name('config.json')
DEFAULT={'gateway_url':'','token':'','poll_seconds':2}

def load():
    if CONFIG.exists():
        try: return {**DEFAULT,**json.loads(CONFIG.read_text(encoding='utf-8'))}
        except Exception: pass
    return DEFAULT.copy()

def save(c): CONFIG.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')

def open_app(app):
    mapping={
        'vscode':['code.exe'],
        'notepad':['notepad.exe'],
        'calculator':['calc.exe'],
        'browser':None,
    }
    if app=='browser':
        webbrowser.open('https://www.google.com'); return 'Navegador aberto.'
    cmd=mapping.get(app)
    if not cmd: return 'Aplicativo não permitido.'
    subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return f'{app} aberto.'

def create_folder(name):
    base=pathlib.Path.home()/ 'Jarvis'
    base.mkdir(exist_ok=True)
    safe=''.join(ch for ch in name if ch.isalnum() or ch in ' _-').strip()
    if not safe: return 'Nome de pasta inválido.'
    target=base/safe
    target.mkdir(exist_ok=True)
    return f'Pasta criada em {target}'

def execute(cmd):
    action=cmd.get('action'); params=cmd.get('params') or {}
    if action=='open_app': return open_app(params.get('app',''))
    if action=='create_folder': return create_folder(params.get('name',''))
    return 'Ação bloqueada.'

def main():
    c=load()
    if not c['gateway_url'] or not c['token']:
        print('Configure local_agent/config.json antes de iniciar.')
        return 1
    url=c['gateway_url'].rstrip('/')
    headers={'X-Agent-Token':c['token']}
    print('Jarvis Local Agent V11 iniciado. Ctrl+C para parar.')
    while True:
        try:
            r=requests.get(url+'/agent/poll',headers=headers,timeout=20); r.raise_for_status()
            for cmd in r.json().get('commands',[]):
                try:
                    result=execute(cmd); ok=True
                except Exception as e:
                    result=str(e); ok=False
                requests.post(url+'/agent/results',headers=headers,json={'command_id':cmd.get('id'),'ok':ok,'result':result},timeout=10)
                print(f"[{cmd.get('id')}] {result}")
        except KeyboardInterrupt: return 0
        except Exception as e: print('Conexão:',e)
        time.sleep(max(1,int(c.get('poll_seconds',2))))

if __name__=='__main__': raise SystemExit(main())
