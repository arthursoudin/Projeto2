import json, os, time, subprocess, pathlib, requests, webbrowser, platform

CONFIG=pathlib.Path(__file__).with_name('config.json')
JARVIS_HOME=pathlib.Path.home()/'Jarvis'
DEFAULT={'gateway_url':'','token':'','poll_seconds':2}

def load():
    if CONFIG.exists():
        try: return {**DEFAULT,**json.loads(CONFIG.read_text(encoding='utf-8'))}
        except Exception: pass
    return DEFAULT.copy()

def safe_name(name):
    return ''.join(ch for ch in str(name) if ch.isalnum() or ch in ' _-.').strip()

def inside_jarvis(path):
    try: pathlib.Path(path).resolve().relative_to(JARVIS_HOME.resolve()); return True
    except ValueError: return False

def open_app(app):
    mapping={'vscode':['code.exe'],'notepad':['notepad.exe'],'calculator':['calc.exe'],'paint':['mspaint.exe']}
    if app=='browser': webbrowser.open('https://www.google.com'); return 'Navegador aberto.'
    cmd=mapping.get(app)
    if not cmd: return 'Aplicativo não permitido.'
    subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return f'{app} aberto.'

def open_folder(name):
    safe=safe_name(name); target=(JARVIS_HOME/safe).resolve() if safe else JARVIS_HOME.resolve()
    if not inside_jarvis(target): return 'Pasta bloqueada.'
    target.mkdir(parents=True,exist_ok=True); os.startfile(str(target)); return f'Pasta aberta: {target}'

def open_file(name):
    safe=safe_name(name); target=(JARVIS_HOME/safe).resolve()
    if not inside_jarvis(target) or not target.is_file(): return 'Arquivo não encontrado ou bloqueado.'
    os.startfile(str(target)); return f'Arquivo aberto: {target}'

def create_folder(name):
    safe=safe_name(name)
    if not safe: return 'Nome de pasta inválido.'
    target=(JARVIS_HOME/safe).resolve()
    if not inside_jarvis(target): return 'Pasta bloqueada.'
    target.mkdir(parents=True,exist_ok=True); return f'Pasta criada em {target}'

def create_file(name,content=''):
    safe=safe_name(name)
    if not safe or pathlib.Path(safe).name!=safe: return 'Nome de arquivo inválido.'
    target=(JARVIS_HOME/safe).resolve()
    if not inside_jarvis(target): return 'Arquivo bloqueado.'
    target.parent.mkdir(parents=True,exist_ok=True); target.write_text(str(content),encoding='utf-8'); return f'Arquivo criado em {target}'

def system_info():
    return {'computer':platform.node(),'os':platform.platform(),'python':platform.python_version(),'home':str(pathlib.Path.home()),'jarvis_folder':str(JARVIS_HOME.resolve())}

def execute(cmd):
    action=cmd.get('action'); p=cmd.get('params') or {}
    if action=='open_app': return open_app(p.get('app',''))
    if action=='open_folder': return open_folder(p.get('name',''))
    if action=='open_file': return open_file(p.get('name',''))
    if action=='create_folder': return create_folder(p.get('name',''))
    if action=='create_file': return create_file(p.get('name',''),p.get('content',''))
    if action=='system_info': return system_info()
    return 'Ação bloqueada.'

def main():
    c=load()
    if not c['gateway_url'] or not c['token']:
        print('Configure local_agent/config.json antes de iniciar.'); return 1
    url=c['gateway_url'].rstrip('/'); headers={'X-Agent-Token':c['token']}
    JARVIS_HOME.mkdir(exist_ok=True)
    print('Jarvis Local Agent V11.1 iniciado. Ctrl+C para parar.')
    while True:
        try:
            r=requests.get(url+'/agent/poll',headers=headers,timeout=20); r.raise_for_status()
            for cmd in r.json().get('commands',[]):
                try: result=execute(cmd); ok=True
                except Exception as e: result=str(e); ok=False
                try: requests.post(url+'/agent/results',headers=headers,json={'command_id':cmd.get('id'),'ok':ok,'result':result},timeout=10)
                except Exception as e: print('Erro enviando resultado:',e)
                print(f"[{cmd.get('id')}] {result}")
        except KeyboardInterrupt: return 0
        except Exception as e: print('Conexão:',e)
        time.sleep(max(1,int(c.get('poll_seconds',2))))

if __name__=='__main__': raise SystemExit(main())
