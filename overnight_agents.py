"""Jarvis V12.7 - laboratório noturno de avaliação contínua.

O loop executa avaliações defensivas e gera relatórios/propostas. Ele NÃO executa
ataques reais e NÃO altera o código de produção automaticamente.
"""
import os, json, time, re, subprocess, datetime as dt, pathlib, hashlib
try:
    import requests
except Exception:
    requests=None

ROOT = pathlib.Path(__file__).resolve().parent
LAB = ROOT / 'overnight_workspace'
REPORTS = LAB / 'reports'
REPORTS.mkdir(parents=True, exist_ok=True)
STATE = LAB / 'state.json'
_LOCAL_CFG=ROOT / 'local_agent' / 'config.json'
try:
    _cfg=json.loads(_LOCAL_CFG.read_text(encoding='utf-8')) if _LOCAL_CFG.exists() else {}
except Exception:
    _cfg={}
GATEWAY_URL=(os.getenv('JARVIS_GATEWAY_URL') or _cfg.get('gateway_url') or '').rstrip('/')
LOCAL_AGENT_TOKEN=(os.getenv('LOCAL_AGENT_TOKEN') or _cfg.get('token') or '')
INTERVAL = int(os.getenv('JARVIS_NIGHT_INTERVAL_MINUTES', '30')) * 60
MAX_CYCLES = int(os.getenv('JARVIS_NIGHT_MAX_CYCLES', '0'))
MODEL = os.getenv('OPENROUTER_MODEL', 'openai/gpt-oss-120b')
API_KEY = os.getenv('OPENROUTER_API_KEY')

ROLES = {
    'qualidade': 'Avalia qualidade, legibilidade, arquitetura, testes e possíveis regressões.',
    'web': 'Pesquisa boas práticas e exemplos públicos atuais relacionados ao problema encontrado.',
    'seguranca': 'Revisa defensivamente autenticação, autorização, segredos, validação, SSRF, path traversal e exposição de dados.',
    'red_team': 'Cria cenários de ataque hipotéticos e seguros para que o agente de segurança possa verificar. Não executa ataques nem fornece exploração operacional.',
    'testes': 'Executa testes locais seguros, checa sintaxe e procura falhas reproduzíveis sem destruir dados.',
    'melhorias': 'Consolida achados, prioriza melhorias e escreve propostas sem modificar a produção.'
}

def load_state():
    try: return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception: return {'cycle':0,'started_at':'','last_cycle':'','status':'idle','history':[]}

def save_state(s): STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')

def files_snapshot():
    out=[]
    for p in ROOT.rglob('*'):
        if any(x in p.parts for x in ['.git','__pycache__','overnight_workspace']): continue
        if p.is_file() and p.suffix in {'.py','.json','.md','.bat','.txt'}:
            try:
                out.append({'path':str(p.relative_to(ROOT)),'size':p.stat().st_size})
            except OSError: pass
    return out[:400]

def run_tests():
    cmd=['python','-m','pytest','-q','tests']
    try:
        p=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=180)
        return {'ok':p.returncode==0,'returncode':p.returncode,'stdout':p.stdout[-6000:],'stderr':p.stderr[-3000:]}
    except Exception as e: return {'ok':False,'error':f'{type(e).__name__}: {e}'}

def compile_check():
    try:
        import py_compile
        bad=[]
        for f in files_snapshot():
            if f['path'].endswith('.py'):
                try: py_compile.compile(str(ROOT/f['path']),doraise=True)
                except Exception as e: bad.append({'file':f['path'],'error':str(e)})
        return {'ok':not bad,'errors':bad[:20]}
    except Exception as e: return {'ok':False,'error':str(e)}

def security_static():
    patterns={
        'possivel_segredo_no_codigo': r'(api[_-]?key|token|secret|password)\s*=\s*[\'\"][^\'\"]{8,}[\'\"]',
        'shell_true': r'subprocess\.(run|Popen|call)\([^\n]*shell\s*=\s*True',
        'eval_exec': r'\b(eval|exec)\s*\(',
        'requests_sem_timeout': r'requests\.(get|post|put|delete)\([^\n]*\)(?![^\n]*timeout\s*=)',
    }
    hits=[]
    for f in files_snapshot():
        p=ROOT/f['path']
        try: text=p.read_text(encoding='utf-8',errors='ignore')
        except Exception: continue
        for name,pat in patterns.items():
            if re.search(pat,text,re.I): hits.append({'rule':name,'file':f['path']})
    return hits[:80]

def web_examples(query):
    try:
        import requests
        from bs4 import BeautifulSoup
        q='Jarvis software agent '+query+' best practices security testing'
        r=requests.get('https://www.google.com/search',params={'q':q},headers={'User-Agent':'Mozilla/5.0'},timeout=12)
        r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser'); vals=[]
        for a in soup.select('a'):
            t=a.get_text(' ',strip=True)
            href=a.get('href','')
            if t and len(t)>30 and href.startswith('http') and 'google.' not in href:
                vals.append({'title':t[:180],'url':href[:500]})
            if len(vals)>=6: break
        return vals
    except Exception as e: return [{'error':f'web indisponível: {type(e).__name__}: {e}'}]

def llm(prompt):
    if not API_KEY: return 'OPENROUTER_API_KEY não configurada; avaliação LLM não executada.'
    try:
        from openai import OpenAI
        c=OpenAI(base_url='https://openrouter.ai/api/v1',api_key=API_KEY)
        r=c.chat.completions.create(model=MODEL,messages=[
            {'role':'system','content':'Você é um avaliador defensivo de software. Seja factual, conciso e não invente evidências. Não proponha ataques operacionais; transforme riscos em testes seguros.'},
            {'role':'user','content':prompt}],temperature=0.15)
        return r.choices[0].message.content or ''
    except Exception as e: return f'LLM indisponível: {type(e).__name__}: {e}'

def cycle(state):
    snapshot=files_snapshot(); tests=run_tests(); compile_result=compile_check(); static=security_static()
    context=json.dumps({'arquivos':snapshot[:180],'testes':tests,'sintaxe':compile_result,'seguranca_estatica':static[-50:]},ensure_ascii=False)
    quality=llm('Avalie a qualidade desta base. Identifique no máximo 5 problemas concretos, classifique por prioridade e cite arquivo quando possível.\n'+context)
    security=llm('Faça uma revisão defensiva de segurança. Use os achados estáticos abaixo, mas valide conceitualmente antes de concluir. Sugira correções e testes seguros.\n'+context)
    scenarios=llm('Crie até 5 cenários de red team APENAS hipotéticos e seguros para testar o sistema. Não dê payloads, exploração passo a passo ou instruções de abuso. Para cada cenário, diga o que o agente de segurança deve verificar.\n'+context)
    webq=' '.join(re.findall(r'\b(?:segurança|security|agent|testing|FastAPI|Streamlit|OpenRouter|multiagent)\w*',quality+' '+security))[:180] or 'multi-agent software testing security'
    web=web_examples(webq)
    improvements=llm('Consolide qualidade, segurança, testes e exemplos web. Produza um backlog de até 8 melhorias, com prioridade, motivo, arquivo provável e teste de aceitação. NÃO altere código.\nQUALIDADE:\n'+quality+'\nSEGURANÇA:\n'+security+'\nRED TEAM:\n'+scenarios+'\nWEB:\n'+json.dumps(web,ensure_ascii=False))
    now=dt.datetime.now().isoformat(timespec='seconds')
    report={'cycle':state.get('cycle',0)+1,'timestamp':now,'roles':ROLES,'tests':tests,'compile':compile_result,'static_security':static,'quality':quality,'security':security,'red_team':scenarios,'web_examples':web,'improvements':improvements}
    out=REPORTS/f'cycle_{report["cycle"]:04d}_{dt.datetime.now():%Y%m%d_%H%M%S}.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    state['cycle']=report['cycle']; state['last_cycle']=now; state['status']='running'; state.setdefault('history',[]).append({'cycle':report['cycle'],'timestamp':now,'tests_ok':tests.get('ok',False),'compile_ok':compile_result.get('ok',False),'report':str(out.relative_to(LAB))})
    state['history']=state['history'][-100:]; save_state(state)
    return report

def remote_config():
    if not requests or not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
        return None
    try:
        r=requests.get(f'{GATEWAY_URL}/overnight/config',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=6)
        r.raise_for_status(); return r.json().get('config')
    except Exception:
        return None

def in_window(start,end,now_time):
    if start==end: return True
    cur=now_time.hour*60+now_time.minute
    sh,sm=map(int,start.split(':')); eh,em=map(int,end.split(':'))
    a=sh*60+sm; b=eh*60+em
    return a<=cur<b if a<b else (cur>=a or cur<b)

def main():
    state=load_state(); state['started_at']=state.get('started_at') or dt.datetime.now().isoformat(timespec='seconds'); save_state(state)
    cycles=0
    print('JARVIS — LABORATÓRIO NOTURNO REMOTO')
    print('A configuração é controlada pelo Dashboard do Render.')
    while True:
        cfg=remote_config()
        if cfg:
            enabled=bool(cfg.get('enabled',False)); interval=max(1,int(cfg.get('interval_minutes',30)))*60; max_cycles=int(cfg.get('max_cycles',0)); start=cfg.get('start_time','22:00'); end=cfg.get('end_time','07:00')
        else:
            enabled=True; interval=INTERVAL; max_cycles=MAX_CYCLES; start='00:00'; end='00:00'
        now_local=dt.datetime.now()
        allowed=enabled and in_window(start,end,now_local)
        if max_cycles and cycles>=max_cycles:
            state['status']='finished'; save_state(state); print('Limite de ciclos atingido.'); time.sleep(30); continue
        if not allowed:
            if state.get('status')!='waiting':
                state['status']='waiting'; save_state(state); print(f'[{now_local:%H:%M}] laboratório aguardando janela/configuração.')
            time.sleep(min(30,interval)); continue
        state['status']='running'; save_state(state)
        try:
            report=cycle(state); cycles+=1
            print(f'[{report["timestamp"]}] ciclo {report["cycle"]} concluído | testes={report["tests"].get("ok")} sintaxe={report["compile"].get("ok")}')
        except KeyboardInterrupt:
            state['status']='stopped'; save_state(state); print('Parado pelo usuário.'); return
        except Exception as e:
            state['status']='error'; state['last_error']=f'{type(e).__name__}: {e}'; save_state(state); print('Erro no ciclo:',state['last_error'])
        # Divide o sono em pequenos blocos para o Dashboard poder pausar/reconfigurar sem CMD.
        slept=0
        while slept<interval:
            time.sleep(min(15,interval-slept)); slept+=15
            new_cfg=remote_config()
            if new_cfg and not new_cfg.get('enabled',False): break

if __name__=='__main__': main()
