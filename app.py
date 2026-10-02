import os, json, asyncio, datetime as dt, uuid, re
from pathlib import Path
import streamlit as st
from openai import OpenAI
import edge_tts
try:
    from honcho import Honcho
except Exception:
    Honcho = None
try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None; BeautifulSoup = None

MODEL=os.getenv('OPENROUTER_MODEL','openai/gpt-oss-120b')
API_KEY=os.getenv('OPENROUTER_API_KEY')
HONCHO_API_KEY=os.getenv('HONCHO_API_KEY')
HONCHO_WORKSPACE=os.getenv('HONCHO_WORKSPACE_ID','jarvis')
HONCHO_USER_ID=os.getenv('HONCHO_USER_ID','user')
HONCHO_ASSISTANT_ID=os.getenv('HONCHO_ASSISTANT_ID','jarvis')
VOICE=os.getenv('EDGE_TTS_VOICE','pt-BR-AntonioNeural')
VOICE_RATE=os.getenv('EDGE_TTS_RATE','+0%')
VOICE_PITCH=os.getenv('EDGE_TTS_PITCH','+0Hz')
MEMORY_FILE=Path('.jarvis_memory.json'); TASKS_FILE=Path('.jarvis_tasks.json')
client=OpenAI(base_url='https://openrouter.ai/api/v1',api_key=API_KEY) if API_KEY else None

import store, voice_io, hashlib, tempfile
DEFAULTS={'messages':[],'tasks':[],'memory':{},'last_action':None,'session_id':uuid.uuid4().hex,'honcho_status':'não configurado','honcho_context':'','pending_pc':None,'mic_n':0,'last_audio_hash':''}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k]=v

def _skey(path): return path.name.removeprefix('.jarvis_').removesuffix('.json')

def load_json(path,default):
    try: return store.load(_skey(path),default)
    except Exception: return default

def save_json(path,data):
    try: return store.save(_skey(path),data)
    except Exception: return False
def refresh_state():
    """Relê tarefas, memória e histórico do armazenamento (WhatsApp e site compartilham os mesmos dados).
    Se a leitura falhar, mantém o que já está na sessão (nunca zera por erro de rede)."""
    for key,path,typ in (('tasks',TASKS_FILE,list),('memory',MEMORY_FILE,dict)):
        d=load_json(path,None)
        if isinstance(d,typ): st.session_state[key]=d
    try:
        h=store.load('pc_history',None)
        if isinstance(h,list): st.session_state.pc_history=h
    except Exception: pass
if 'pc_history' not in st.session_state: st.session_state.pc_history=[]
refresh_state()
if 'pc_profile' not in st.session_state: st.session_state.pc_profile=store.load('pc_profile',{})

@st.cache_resource(show_spinner=False)
def get_honcho():
    if not HONCHO_API_KEY or Honcho is None: return None
    try: return Honcho(workspace_id=HONCHO_WORKSPACE,api_key=HONCHO_API_KEY,environment='production')
    except Exception: return None

def honcho_objects():
    h=get_honcho()
    if not h: return None,None,None
    try:
        user=h.peer(HONCHO_USER_ID); assistant=h.peer(HONCHO_ASSISTANT_ID)
        session=h.session(st.session_state.session_id); session.add_peers([user,assistant])
        return h,user,assistant
    except Exception as e:
        st.session_state.honcho_status=f'erro: {e}'; return None,None,None

def honcho_save_turn(user_text,assistant_text):
    h,user,assistant=honcho_objects()
    if not h: return False
    try:
        h.session(st.session_state.session_id).add_messages([user.message(str(user_text)),assistant.message(str(assistant_text))])
        st.session_state.honcho_status='conectado • turno salvo'; return True
    except Exception as e:
        st.session_state.honcho_status=f'erro ao salvar: {e}'; return False

def honcho_context(query='O que é importante lembrar sobre este usuário?'):
    h,user,_=honcho_objects()
    if not h: return ''
    try:
        context=h.session(st.session_state.session_id).context(summary=True,tokens=5000)
        return str(context)[:18000]
    except Exception:
        try: return str(user.chat(query))[:8000]
        except Exception as e: st.session_state.honcho_status=f'erro ao consultar: {e}'; return ''

def honcho_search(query):
    _,user,_=honcho_objects()
    if not user: return 'Honcho não está configurado.'
    try: return str(user.search(query))[:10000]
    except Exception as e: return f'Erro na busca de memória: {e}'

try:
    from skills import load_catalog
    SKILLS=load_catalog()
except Exception:
    SKILLS={}

def detect_skills(text):
    low=text.lower(); found=[n for n,s in SKILLS.items() if any(k in low for k in s['keywords'])]; return found or ['planejamento']

from core import now, current_time, iso_now, calculator, parse_due, recurrence_from_text, clean_task_text
import core
from agents import wants_team, strip_trigger, AGENTS
from tool_registry import tool_rows, tools_for_agent
import orchestrator, devices

def next_task_id():
    return max([int(t.get('id',0)) for t in st.session_state.tasks] or [0])+1

def create_task(text, priority='normal', due=None, recurrence=''):
    t={'id':next_task_id(),'text':clean_task_text(text),'priority':priority,'status':'pending','created_at':iso_now(),'due_at':due or '','recurrence':recurrence,'completed_at':''}
    st.session_state.tasks.append(t); save_json(TASKS_FILE,st.session_state.tasks); return t

def complete_task(task_id):
    for t in st.session_state.tasks:
        if int(t.get('id'))==int(task_id):
            t['status']='done'; t['completed_at']=iso_now(); save_json(TASKS_FILE,st.session_state.tasks); return t
    return None

def delete_task(task_id):
    old=len(st.session_state.tasks); st.session_state.tasks=[t for t in st.session_state.tasks if int(t.get('id'))!=int(task_id)]
    save_json(TASKS_FILE,st.session_state.tasks); return len(st.session_state.tasks)<old

def task_status_text(t):
    if t.get('status')=='done': return 'concluída'
    due=t.get('due_at')
    if due:
        try:
            d=dt.datetime.fromisoformat(due)
            if d < now(): return 'atrasada'
        except Exception: pass
    return 'pendente'

def task_summary():
    pending=[t for t in st.session_state.tasks if t.get('status')!='done']
    overdue=[t for t in pending if task_status_text(t)=='atrasada']
    return {'total':len(st.session_state.tasks),'pendentes':len(pending),'atrasadas':len(overdue),'concluidas':len(st.session_state.tasks)-len(pending)}

def web_search(query):
    if not requests: return 'requests não está disponível.'
    try:
        r=requests.get('https://www.google.com/search',params={'q':query},headers={'User-Agent':'Mozilla/5.0'},timeout=10); r.raise_for_status()
        if BeautifulSoup:
            soup=BeautifulSoup(r.text,'html.parser'); out=[]
            for b in soup.select('div'):
                x=b.get_text(' ',strip=True)
                if 80<len(x)<400: out.append(x)
                if len(out)>=5: break
            return '\n'.join(out) or 'Nenhum resultado resumível encontrado.'
        return r.text[:3000]
    except Exception as e: return f'Erro na pesquisa: {e}'

def choose_tool(text):
    l=text.lower()
    if any(x in l for x in ['quanto é','calcule','calcular']): return 'calculator'
    if any(x in l for x in ['que horas','horário','horario','data de hoje']): return 'time'
    if any(x in l for x in ['crie uma tarefa','adiciona uma tarefa','adicione uma tarefa','nova tarefa','criar tarefa','me lembre de','lembre de']): return 'task'
    if any(x in l for x in ['conclua a tarefa','concluir tarefa','finalize a tarefa','marque a tarefa']): return 'complete_task'
    if any(x in l for x in ['apague a tarefa','exclua a tarefa','delete a tarefa']): return 'delete_task'
    if any(x in l for x in ['lembre de','lembra de','guarde que','memorize']): return 'memory'
    if any(x in l for x in ['pesquise','procure na internet','pesquisa na web']): return 'web'
    if any(x in l for x in ['busque na memória','procure na memória','o que você lembra','você lembra']): return 'memory_search'
    return None

def extract_task_id(text):
    m=re.search(r'(?:tarefa\s*#?|#)(\d+)',text.lower()); return int(m.group(1)) if m else None

def execute_tool(text):
    tool=choose_tool(text)
    if tool=='calculator':
        e=text.lower()
        for p in ['quanto é','calcule','calcular']: e=e.replace(p,'')
        return tool,calculator(e.strip())
    if tool=='time': return tool,current_time()
    if tool=='task':
        priority='high' if any(x in text.lower() for x in ['alta prioridade','urgente','urgência']) else ('low' if 'baixa prioridade' in text.lower() else 'normal')
        due=parse_due(text); recurrence=recurrence_from_text(text); t=create_task(text,priority,due,recurrence)
        when=f" • prazo: {dt.datetime.fromisoformat(due).strftime('%d/%m/%Y %H:%M')}" if due else ''
        rec=f" • recorrência: {recurrence}" if recurrence else ''
        return tool,f"Tarefa #{t['id']} criada: {t['text']}{when}{rec}"
    if tool=='complete_task':
        tid=extract_task_id(text); t=complete_task(tid) if tid else None
        return tool,(f"Tarefa #{tid} concluída." if t else 'Informe o número da tarefa, por exemplo: conclua a tarefa #3.')
    if tool=='delete_task':
        tid=extract_task_id(text); ok=delete_task(tid) if tid else False
        return tool,(f"Tarefa #{tid} excluída." if ok else 'Informe o número da tarefa, por exemplo: apague a tarefa #3.')
    if tool=='memory':
        c=text
        for p in ['lembre de','lembra de','guarde que','memorize']: c=c.lower().replace(p,'',1)
        result=save_memory_item(f'memoria_{len(st.session_state.memory)+1}',c.strip()); return tool,result
    if tool=='memory_search':
        q=text
        for p in ['busque na memória','procure na memória','o que você lembra','você lembra']: q=q.lower().replace(p,'',1)
        return tool,honcho_search(q.strip() or 'informações importantes sobre o usuário')
    if tool=='web':
        q=text
        for p in ['pesquise','procure na internet','pesquisa na web']: q=q.lower().replace(p,'',1)
        return tool,web_search(q.strip())
    return None,None

def system_prompt(memory_context=''):
    return '''Você é Jarvis, assistente pessoal em português do Brasil. Seja direto, inteligente, útil e honesto. Use memória e tarefas como contexto, sem inventar fatos. Se algo estiver incerto, diga isso. Quando uma ferramenta já tiver executado uma ação, explique o resultado sem fingir que fará outra ação.\nSkills: %s\nControle local do PC: somente por agente autorizado e ações permitidas. Rotinas agendadas rodam no PC pelo agente local, mesmo com o app fechado. Só diga que algo foi feito se o resultado da ferramenta tiver ok=true; se houver erro, explique o erro e como resolver. Se estiver AGUARDANDO CONFIRMAÇÃO, nada foi executado ainda.\nMemória local: %s\nTarefas: %s\nResumo de tarefas: %s\nMemória Honcho recuperada: %s\nÚltimas ações no PC: %s\nPerfil do PC: %s''' % (json.dumps(list(SKILLS),ensure_ascii=False),json.dumps(st.session_state.memory,ensure_ascii=False),json.dumps(st.session_state.tasks,ensure_ascii=False),json.dumps(task_summary(),ensure_ascii=False),memory_context or 'nenhuma',json.dumps(st.session_state.pc_history[-8:],ensure_ascii=False),json.dumps(st.session_state.pc_profile,ensure_ascii=False))

def ask_llm(user_text,tool_result=None,memory_context=''):
    if not client: return 'OPENROUTER_API_KEY não configurada.'
    msgs=[{'role':'system','content':system_prompt(memory_context)}]+st.session_state.messages[-12:]
    if tool_result: msgs.append({'role':'system','content':f'Resultado da ferramenta executada: {tool_result}'})
    msgs.append({'role':'user','content':user_text})
    r=client.chat.completions.create(model=MODEL,messages=msgs,temperature=0.4); return r.choices[0].message.content

VOICES=['pt-BR-AntonioNeural','pt-BR-FranciscaNeural']
SPEEDS={'Lenta':'-15%','Normal':None,'Rápida':'+15%'}

async def make_audio(text,filename):
    voice=st.session_state.get('voice_name') or VOICE
    rate=SPEEDS.get(st.session_state.get('voice_speed','Normal')) or VOICE_RATE
    await edge_tts.Communicate(text=str(text),voice=voice,rate=rate,pitch=VOICE_PITCH).save(filename); return filename

def speak(text):
    """Fala a resposta (sem markdown/emoji/código). Não deixa arquivos temporários para trás."""
    spoken=voice_io.clean_for_speech(text)
    if not spoken: return
    path=os.path.join(tempfile.gettempdir(),f'jarvis_{uuid.uuid4().hex[:10]}.mp3')
    try:
        asyncio.run(make_audio(spoken,path))
        with open(path,'rb') as f: data=f.read()
    finally:
        try: os.remove(path)
        except OSError: pass
    st.audio(data,format='audio/mp3',autoplay=True)

GATEWAY_URL=os.getenv('JARVIS_GATEWAY_URL','').rstrip('/')
LOCAL_AGENT_TOKEN=os.getenv('LOCAL_AGENT_TOKEN','')

def get_agent_status():
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN: return {'ok':False,'error':'Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN no Render.'}
    try:
        r=requests.get(f'{GATEWAY_URL}/agent/status',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=6)
        if r.status_code==401: return {'ok':False,'error':'Token recusado pelo gateway.'}
        r.raise_for_status(); return r.json()
    except Exception as e: return {'ok':False,'error':f'Gateway não respondeu ({type(e).__name__}). O plano grátis do Render dorme; tente de novo em instantes.'}

def get_security_status():
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN: return {'ok':False,'error':'Gateway não configurado.'}
    try:
        r=requests.get(f'{GATEWAY_URL}/security/status',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=6); return r.json()
    except Exception as e: return {'ok':False,'error':str(e)}

def get_security_approvals():
    try:
        r=requests.get(f'{GATEWAY_URL}/security/approvals',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=6); return r.json().get('approvals',[])
    except Exception: return []

def security_decide(approval_id, decision):
    try:
        r=requests.post(f'{GATEWAY_URL}/security/{decision}/{approval_id}',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=8); return r.json()
    except Exception as e: return {'ok':False,'error':str(e)}

def security_kill(enabled):
    try:
        r=requests.post(f'{GATEWAY_URL}/security/kill-switch',json={'enabled':enabled},headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=8); return r.json()
    except Exception as e: return {'ok':False,'error':str(e)}

def security_policy_save(data):
    try:
        r=requests.post(f'{GATEWAY_URL}/security/policy',json=data,headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=8); return r.json()
    except Exception as e: return {'ok':False,'error':str(e)}

def queue_pc_action(action, params=None, wait_seconds=15):
    """Envia a ação ao agente local e aguarda o resultado real."""
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
        return {'ok':False,'error':'Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN no Render.'}
    if not requests:
        return {'ok':False,'error':'requests não está disponível.'}
    headers={'X-Agent-Token':LOCAL_AGENT_TOKEN}
    try:
        r=requests.post(f'{GATEWAY_URL}/agent/commands', json={'action':action,'params':params or {},'agent':'app','source':'app'}, headers=headers, timeout=10)
        if r.status_code not in (200,201):
            try: return {'ok':False,'error':r.json().get('detail',r.text)}
            except Exception: return {'ok':False,'error':r.text}
        queued=r.json()
        if queued.get('pending_approval'):
            return {'ok':False,'pending_approval':True,'approval':queued.get('approval'),'action':action,'message':'Ação enviada para aprovação de segurança.'}
        if not queued.get('ok') or not queued.get('command_id'): return queued
        command_id=queued['command_id']
        import time
        deadline=time.time()+max(3,int(wait_seconds))
        while time.time() < deadline:
            rr=requests.get(f'{GATEWAY_URL}/agent/results',headers=headers,timeout=10); rr.raise_for_status()
            for item in rr.json().get('results',[]):
                if item.get('command_id')==command_id:
                    res=item.get('result') or {}
                    return {'ok':bool(res.get('ok', item.get('ok'))),'command_id':command_id,'action':action,'result':res}
            time.sleep(1)
        return {'ok':False,'command_id':command_id,'action':action,'error':'O agente local não respondeu no tempo esperado. Verifique se start_agent.bat está aberto.'}
    except Exception as e:
        return {'ok':False,'error':str(e)}

from pc_control import parse_pc_commands, PERMISSIONS, CONFIRM_ACTIONS, describe_step, is_confirm, is_cancel

def _run_pc_plan(steps, confirmed=False):
    """Executa os passos em ordem. Ações sensíveis esperam confirmação. Para no primeiro erro."""
    done=[]
    for i,(action,params) in enumerate(steps):
        if action == 'schedule_invalid':
            done.append({'acao':'agendar','ok':False,'resultado':{'ok':False,'error':params.get('error')}}); return done,'error'
        if action in CONFIRM_ACTIONS and not confirmed:
            st.session_state.pending_pc=steps[i:]
            return done,'confirm'
        p=dict(params)
        if action in CONFIRM_ACTIONS: p['confirmed']=True
        r=queue_pc_action(action,p)
        done.append({'acao':describe_step(action,params),'ok':r.get('ok'),'resultado':r.get('result') or r.get('error')})
        if not r.get('ok'): return done,'error'
    return done,'ok'

def remember_pc(done):
    """Guarda histórico recente e o perfil do PC (persistem no Supabase, se configurado)."""
    try:
        for d in done:
            if d['acao'] in ('listar rotinas',) or d['acao'].startswith('read_log'): continue
            st.session_state.pc_history.append({'quando':dt.datetime.now().strftime('%d/%m %H:%M'),'acao':d['acao'][:120],'ok':bool(d['ok'])})
            r=d.get('resultado')
            if d['acao'].startswith('system_info') and d['ok'] and isinstance(r,dict):
                st.session_state.pc_profile={k:r[k] for k in ('computer','os','processor','cpu_threads','ram_total_gb','disco_total_gb') if k in r}
                store.save('pc_profile',st.session_state.pc_profile)
        st.session_state.pc_history=st.session_state.pc_history[-40:]
        store.save('pc_history',st.session_state.pc_history)
    except Exception: pass

def run_pc_plan(steps, confirmed=False):
    done,status=_run_pc_plan(steps,confirmed); remember_pc(done); return done,status

def save_memory_item(key,value):
    st.session_state.memory[str(key)]=str(value)
    save_json(MEMORY_FILE,st.session_state.memory)
    return f'Memória local salva: {value}'

def fmt_due(t):
    try: return dt.datetime.fromisoformat(t['due_at']).strftime('%d/%m %H:%M') if t.get('due_at') else '—'
    except Exception: return '—'

def run_team(goal):
    """V12.7: o Planejador divide o objetivo e os agentes especialistas executam. Equipes nunca apagam nada."""
    brain=core.Brain(run_pc=queue_pc_action,llm=core.make_llm(),agent_status=get_agent_status,channel='app')
    out=brain.team_run(goal); refresh_state(); st.session_state.last_team=out; return out

st.set_page_config(page_title='Jarvis V13.1',page_icon='J',layout='wide')

# V13.1 — Dashboard 2.0: camada visual centralizada, sem alterar as permissões.
st.markdown('''
<style>
:root { --jarvis-border: rgba(148,163,184,.18); --jarvis-muted:#94a3b8; }
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }
.jarvis-hero { padding: 1.25rem 1.4rem; border: 1px solid var(--jarvis-border); border-radius: 18px; background: linear-gradient(135deg, rgba(15,23,42,.96), rgba(30,41,59,.82)); margin-bottom: 1rem; }
.jarvis-hero h1 { margin: 0; font-size: 2.1rem; letter-spacing: .08em; }
.jarvis-hero p { margin: .35rem 0 0; color: var(--jarvis-muted); }
.jarvis-card { border: 1px solid var(--jarvis-border); border-radius: 16px; padding: 1rem; background: rgba(15,23,42,.45); min-height: 100px; }
.jarvis-label { color: var(--jarvis-muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }
.jarvis-value { font-size: 1.45rem; font-weight: 700; margin-top: .3rem; }
.jarvis-ok { color:#86efac; } .jarvis-warn { color:#facc15; } .jarvis-bad { color:#fca5a5; }
[data-testid="stMetric"] { border: 1px solid var(--jarvis-border); padding: .75rem; border-radius: 14px; background: rgba(15,23,42,.35); }

.jarvis-map { display:flex; flex-wrap:wrap; align-items:center; gap:.7rem; padding:1rem; border:1px solid var(--jarvis-border); border-radius:18px; background:rgba(2,6,23,.45); overflow-x:auto; }
.jarvis-node { min-width:145px; max-width:210px; min-height:76px; padding:.8rem .9rem; border:1px solid var(--jarvis-border); border-radius:14px; position:relative; background:rgba(15,23,42,.72); box-shadow:0 6px 22px rgba(0,0,0,.12); }
.jarvis-node:not(:last-child)::after { content:'→'; position:absolute; right:-.62rem; top:50%; transform:translateY(-50%); color:var(--jarvis-muted); z-index:2; font-weight:700; }
.jarvis-node-title { font-weight:700; font-size:.86rem; }
.jarvis-node-state { color:var(--jarvis-muted); font-size:.72rem; margin-top:.35rem; text-transform:uppercase; letter-spacing:.05em; }
.jarvis-node-running { border-color:rgba(250,204,21,.65); box-shadow:0 0 18px rgba(250,204,21,.12); }
.jarvis-node-error { border-color:rgba(248,113,113,.75); }
.jarvis-node-ok { border-color:rgba(134,239,172,.55); }
.jarvis-node-idle { border-color:rgba(148,163,184,.28); }
</style>
<div class="jarvis-hero"><h1>J A R V I S</h1><p>Command Center • Dashboard 2.0 • Core Integrado • Agent Map</p></div>
''', unsafe_allow_html=True)
st.title('Jarvis V13.1'); st.caption('Agente pessoal • Memória • Tarefas • PC • Computer Agent • Permissões • Rotinas • Voz • Dashboard 2.0 • WhatsApp • Multiagentes')
with st.sidebar:
    st.header('Sistema'); st.metric('Modelo',MODEL.split('/')[-1][:24]); st.metric('Skills',len(SKILLS)); st.metric('Tarefas',len(st.session_state.tasks)); st.metric('Pendentes',task_summary()['pendentes']); st.metric('Memórias locais',len(st.session_state.memory)); st.write('**PC Agent:**', 'configurado' if (GATEWAY_URL and LOCAL_AGENT_TOKEN) else 'não configurado')
    _stt=store.status(); st.caption(('✅ ' if _stt['ok'] and _stt['backend']=='supabase' else '⚠️ ')+'Armazenamento: '+_stt['backend']+' — '+_stt['detalhe'])
    with st.expander('🔊 Voz'):
        st.toggle('Responder em voz',value=True,key='speak_on')
        st.selectbox('Voz',[VOICE]+[v for v in VOICES if v!=VOICE],key='voice_name')
        st.selectbox('Velocidade',list(SPEEDS),index=1,key='voice_speed')
        st.caption('🎤 Microfone: '+voice_io.status_text())
    st.write('**Honcho:**',st.session_state.honcho_status)
    if HONCHO_API_KEY: st.success('HONCHO_API_KEY configurada')
    else: st.warning('HONCHO_API_KEY não configurada')
    if st.button('Nova conversa'): st.session_state.messages=[]; st.session_state.session_id=uuid.uuid4().hex; st.rerun()



def get_overnight_config():
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
        return {'ok':False,'error':'Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN no Render.'}
    try:
        r=requests.get(f'{GATEWAY_URL}/overnight/config',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=6)
        r.raise_for_status(); return r.json()
    except Exception as e:
        return {'ok':False,'error':f'Não foi possível consultar o laboratório: {type(e).__name__}: {e}'}

def save_overnight_config(cfg):
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
        return {'ok':False,'error':'Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN no Render.'}
    try:
        r=requests.post(f'{GATEWAY_URL}/overnight/config',json=cfg,headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=8)
        r.raise_for_status(); return r.json()
    except Exception as e:
        return {'ok':False,'error':f'Não foi possível salvar a configuração: {type(e).__name__}: {e}'}

tabs=st.tabs(['Chat','Dashboard','Tarefas','Automações','Memória','Honcho','Skills','Sistema','WhatsApp','Agentes','Tools','Laboratório Noturno','Computer Agent','Segurança','Command Center','Agent Map'])
with tabs[0]:
    for m in st.session_state.messages:
        with st.chat_message(m['role']): st.markdown(m['content'])
    spoken_in=False
    if voice_io.configured() and hasattr(st,'audio_input'):
        audio=st.audio_input('🎤 Fale com o Jarvis: grave, envie e ele responde em voz',key=f"mic_{st.session_state.mic_n}")
    else:
        audio=None; st.caption('🎤 Para falar pelo microfone, configure OPENROUTER_API_KEY no Render.' if not voice_io.configured() else '🎤 Atualize o Streamlit para usar o microfone.')
    prompt=st.chat_input('Fale com o Jarvis...')
    if audio is not None and not prompt:
        data=audio.getvalue(); h=hashlib.md5(data).hexdigest()
        if h!=st.session_state.last_audio_hash:
            st.session_state.last_audio_hash=h; st.session_state.mic_n+=1
            try: prompt=voice_io.transcribe(data); spoken_in=True
            except voice_io.VoiceError as e: st.warning(str(e))
    if prompt:
        st.session_state.messages.append({'role':'user','content':prompt})
        with st.chat_message('user'):
            st.markdown(prompt)
            if spoken_in: st.caption('🎤 transcrito da sua voz')
        skills=detect_skills(prompt); tool=None; result=None; confirm_note=''; team_answer=None
        pending=st.session_state.pending_pc
        if pending:
            st.session_state.pending_pc=None
            if is_confirm(prompt):
                done,status=run_pc_plan(pending,confirmed=True); tool='computer'; result=json.dumps({'confirmado':True,'acoes':done,'status':status},ensure_ascii=False)
            elif is_cancel(prompt):
                tool='computer'; result='O usuário cancelou a ação pendente. Nada foi executado.'
        if tool is None and wants_team(prompt):
            with st.spinner('Equipe de agentes trabalhando...'):
                try: out=run_team(strip_trigger(prompt)); team_answer=out['reply']; tool='equipe'; result=json.dumps(out['trace'],ensure_ascii=False)[:6000]
                except Exception as e: team_answer=f'A equipe encontrou um erro ({type(e).__name__}). Tente de novo ou peça por partes.'; tool='equipe'; result=str(e)[:300]
        if tool is None:
            steps=parse_pc_commands(prompt)
            if steps:
                done,status=run_pc_plan(steps); tool='computer'
                result=json.dumps({'acoes':done,'status':status},ensure_ascii=False)
                if status=='confirm':
                    todo=', '.join(describe_step(a,p) for a,p in st.session_state.pending_pc if a in CONFIRM_ACTIONS)
                    result+=f' | AGUARDANDO CONFIRMAÇÃO do usuário para: {todo}. Nada disso foi executado ainda.'
                    confirm_note=f'\n\n⚠️ **Confirma?** {todo} — responda **sim** ou **não**. (Itens apagados vão para a lixeira do Jarvis e podem ser restaurados.)'
            else: tool,result=execute_tool(prompt)
        context=honcho_context(prompt); st.session_state.honcho_context=context
        st.session_state.last_action={'skills':skills,'tool':tool,'result':result,'session_id':st.session_state.session_id}
        with st.chat_message('assistant'):
            try:
                answer=(team_answer if team_answer else ask_llm(prompt,result,context))+confirm_note; st.markdown(answer); st.session_state.messages.append({'role':'assistant','content':answer}); honcho_save_turn(prompt,answer)
                if spoken_in or st.session_state.get('speak_on',True):
                    try: speak(answer)
                    except Exception as e: st.caption(f'Áudio indisponível: {e}')
            except Exception as e: st.error(f'Erro no Jarvis: {e}')
with tabs[1]:
    st.subheader('Dashboard')
    st.session_state.dash_since=dt.datetime.now().timestamp()   # toda ação do usuário reinicia o relógio de auto-atualização
    _frag=st.fragment(run_every=10) if hasattr(st,'fragment') else (lambda f: f)
    @_frag
    def dashboard_panel():
        if dt.datetime.now().timestamp()-st.session_state.get('dash_since',0)>600:
            st.info('Atualização automática pausada (10 min sem uso).')
            if st.button('Retomar',key='dash_resume'): st.session_state.dash_since=dt.datetime.now().timestamp()
            return
        s_=get_agent_status(); info=(s_.get('info') or {}) if s_.get('ok') else {}
        if not s_.get('ok'): st.error(s_.get('error') or 'Sem status do agente.')
        online=bool(s_.get('online')); n=lambda v,suf='': f'{v}{suf}' if v is not None else '—'
        c=st.columns(5)
        c[0].metric('Agente','🟢 Online' if online else '🔴 Offline')
        c[1].metric('CPU',n(None if info.get('cpu_percent') is None else round(info['cpu_percent']),'%'))
        c[2].metric('RAM',n(info.get('ram_em_uso_percent'),'%'),f"{info['ram_livre_gb']} GB livres" if info.get('ram_livre_gb') is not None else None,delta_color='off')
        c[3].metric('Disco livre',n(info.get('disco_livre_gb'),' GB'),f"de {info['disco_total_gb']} GB" if info.get('disco_total_gb') is not None else None,delta_color='off')
        c[4].metric('Ligado há',info.get('ligado_ha') or '—')
        if s_.get('ok'):
            age=s_.get('age_seconds')
            st.caption(f"{info.get('computer','?')} · agente v{info.get('version','?')} · visto há {int(age)}s" if age is not None else 'O agente ainda não se conectou.')
            if not online: st.warning('Agente offline: abra local_agent/start_agent.bat no PC.')
        h=[x for x in (s_.get('history') or []) if x.get('cpu') is not None or x.get('ram') is not None]
        if len(h)>=2:
            import pandas as pd
            df=pd.DataFrame({'CPU %':[x.get('cpu') for x in h],'RAM %':[x.get('ram') for x in h]},index=pd.to_datetime([x['t'] for x in h],unit='s'))
            try: df.index=df.index.tz_localize('UTC').tz_convert('America/Sao_Paulo')
            except Exception: pass
            st.line_chart(df,height=180)
        st.markdown('**Visão geral**')
        sm=task_summary(); d=st.columns(4)
        d[0].metric('Tarefas pendentes',sm['pendentes'],f"{sm['atrasadas']} atrasadas" if sm['atrasadas'] else None,delta_color='inverse')
        d[1].metric('Rotinas ativas',n(info.get('rotinas_ativas')))
        pr=info.get('proxima_rotina'); d[2].metric('Próxima rotina',pr['quando'] if isinstance(pr,dict) else '—')
        if isinstance(pr,dict) and pr.get('resumo'): d[2].caption(pr['resumo'][:60])
        d[3].metric('Fila de comandos',s_.get('queued_commands',0) if s_.get('ok') else '—')
        st.markdown('**Canais**'); wa=s_.get('whatsapp') if s_.get('ok') else None; w=st.columns(4)
        if wa is None:
            w[0].metric('WhatsApp','—'); st.caption('Sem dados do gateway (ou gateway antigo: faça o deploy da V12.7).')
        else:
            w[0].metric('WhatsApp','Ativo ✅' if wa.get('configured') else 'Não configurado ⚠️')
            w[1].metric('Mensagens hoje',wa.get('messages_today',0)); w[2].metric('Último contato',wa.get('last_message_at') or '—'); w[3].metric('Números autorizados',wa.get('allowed_count',0))
            if not wa.get('configured') and wa.get('missing'): st.caption('Faltam no gateway: '+', '.join(wa['missing'])+' (veja a aba WhatsApp).')
            if wa.get('last_error'): st.caption('⚠️ Último erro do WhatsApp: '+wa['last_error'])
            if wa.get('log'): st.table(wa['log'][:6])
        cache=st.session_state.get('_stt_cache'); now_=dt.datetime.now().timestamp()
        if not cache or now_-cache[0]>60: cache=(now_,store.status()); st.session_state._stt_cache=cache
        stt_=cache[1]; e=st.columns(3)
        e[0].metric('Armazenamento',stt_['backend'].capitalize()+(' ✅' if stt_['ok'] and stt_['backend']=='supabase' else ' ⚠️'))
        e[1].metric('Memória Honcho','Ativa' if HONCHO_API_KEY else 'Desligada')
        e[2].metric('Microfone',voice_io.provider()['name'] if voice_io.configured() else 'Desligado')
        if stt_['backend']=='arquivo': st.caption('⚠️ '+stt_['detalhe'])
        st.markdown('**Últimas ações no PC**')
        hist=st.session_state.pc_history[-8:][::-1]
        st.table(hist) if hist else st.caption('Nenhuma ação ainda. Peça algo ao Jarvis no chat.')
        st.markdown('**Próximas tarefas**'); pend_=core.pending_tasks(st.session_state.tasks)[:5]
        if pend_: st.table([{'#':t['id'],'Tarefa':t['text'],'Prazo':fmt_due(t),'Status':task_status_text(t)} for t in pend_])
        else: st.caption('Nenhuma tarefa pendente.')
        if st.button('Ver rotinas do PC',key='dash_routines'):
            rr_=queue_pc_action('schedule_list',{}); rows_=((rr_.get('result') or {}).get('rotinas')) or []
            st.table(rows_) if rows_ else st.info(rr_.get('error') or 'Nenhuma rotina criada. Peça no chat, por exemplo: "todo dia às 9h abra o vs code".')
        if st.button('Ver log do agente local',key='dash_log'):
            lg=queue_pc_action('read_log',{'lines':15}); st.code('\n'.join(((lg.get('result') or {}).get('linhas')) or [])[-3000:] or (lg.get('error') or 'Log vazio.'))
    dashboard_panel()
with tabs[2]:
    st.subheader('Gerenciador de tarefas')
    summary=task_summary(); c1,c2,c3,c4=st.columns(4); c1.metric('Total',summary['total']); c2.metric('Pendentes',summary['pendentes']); c3.metric('Atrasadas',summary['atrasadas']); c4.metric('Concluídas',summary['concluidas'])
    if st.button('Atualizar tarefas'): st.rerun()
    if not st.session_state.tasks: st.info('Nenhuma tarefa criada. Você pode pedir ao Jarvis para criar uma.')
    for t in sorted(st.session_state.tasks,key=lambda x:(x.get('status')=='done',x.get('due_at') or '9999')):
        with st.container(border=True):
            cols=st.columns([0.08,0.48,0.16,0.18,0.10])
            cols[0].write(f"#{t['id']}")
            cols[1].write(f"**{t['text']}**")
            cols[2].write(t.get('priority','normal'))
            due=t.get('due_at')
            cols[3].write(dt.datetime.fromisoformat(due).strftime('%d/%m/%Y %H:%M') if due else 'sem prazo')
            if t.get('status')!='done':
                if cols[4].button('Concluir',key=f"done_{t['id']}"): complete_task(t['id']); st.rerun()
            else: cols[4].write('Concluída')
            if t.get('recurrence'): st.caption(f"Recorrência: {t['recurrence']} • Status: {task_status_text(t)}")
with tabs[3]:
    st.subheader('Automações')
    st.caption('Rotinas rodam no seu PC pelo agente local, mesmo com o Render dormindo. Exemplos: "todo dia às 9h abra o vs code", "toda segunda e quarta às 8h abra a pasta Estudos", "daqui a 10 minutos abra a calculadora", "a cada 30 minutos abra o navegador".')
    st.markdown('**Rotinas no PC**')
    c1,c2,c3,c4=st.columns([2,1,1,1])
    rid=c1.number_input('Nº da rotina',min_value=1,step=1,value=1,label_visibility='collapsed')
    if c2.button('Atualizar'): st.session_state.routines=queue_pc_action('schedule_list',{})
    if c3.button('Pausar/Ativar'):
        rows=((st.session_state.get('routines') or {}).get('result') or {}).get('rotinas',[])
        cur=next((r for r in rows if r.get('id')==int(rid)),None)
        st.session_state.routines_msg=queue_pc_action('schedule_toggle',{'id':int(rid),'enabled':not (cur or {}).get('ativa',False)}); st.session_state.routines=queue_pc_action('schedule_list',{})
    if c4.button('Remover'):
        st.session_state.routines_msg=queue_pc_action('schedule_remove',{'id':int(rid)}); st.session_state.routines=queue_pc_action('schedule_list',{})
    if st.session_state.get('routines_msg'): m=st.session_state.routines_msg; (st.success if m.get('ok') else st.error)(((m.get('result') or {}).get('message')) or m.get('error') or 'Falha.')
    rr=st.session_state.get('routines')
    if rr and rr.get('ok'):
        rows=(rr.get('result') or {}).get('rotinas',[])
        st.table(rows) if rows else st.info('Nenhuma rotina criada. Peça no chat, por exemplo: "todo dia às 9h abra o vs code".')
    elif rr: st.error(rr.get('error') or 'O agente local não respondeu. Abra o start_agent.bat.')
    st.markdown('**Tarefas com prazo**')
    pending=[t for t in st.session_state.tasks if t.get('status')!='done']
    if pending:
        for t in pending:
            status=task_status_text(t); label='Atrasada' if status=='atrasada' else 'Agendada' if t.get('due_at') else 'Sem horário'
            st.write(f"Tarefa #{t['id']} — {t['text']} — {label}")
    else: st.info('Nenhuma automação/tarefa pendente.')
with tabs[4]:
    st.subheader('Memória local de fallback'); st.json(st.session_state.memory) if st.session_state.memory else st.info('Nenhuma memória local salva.')
with tabs[5]:
    st.subheader('Memória Honcho'); st.write('Workspace:',HONCHO_WORKSPACE); st.write('Peer:',HONCHO_USER_ID); st.write('Sessão:',st.session_state.session_id); st.write('Status:',st.session_state.honcho_status)
    if st.button('Testar memória Honcho'):
        c=honcho_context('Quais informações importantes você tem sobre este usuário?'); st.session_state.honcho_context=c
        if c: st.success('Memória recuperada.'); st.code(c[:12000])
        else: st.warning('Não foi possível recuperar memória. Verifique HONCHO_API_KEY.')
with tabs[6]:
    st.subheader('Skills 2.0')
    st.caption('Catálogo externo de habilidades. As descrições e palavras-chave ficam em skills/catalog.json para facilitar expansão sem mexer no núcleo.')
    c1,c2=st.columns(2); c1.metric('Skills carregadas',len(SKILLS)); c2.metric('Palavras-chave',sum(len(x.get('keywords',[])) for x in SKILLS.values()))
    for n,s in SKILLS.items():
        with st.expander(n):
            st.write(s.get('description',''))
            st.write('**Palavras-chave:**',', '.join(s.get('keywords',[])))
    st.info('Próxima evolução: skills executáveis poderão registrar ferramentas próprias, mantendo as permissões do Jarvis Core.')
with tabs[7]:
    st.json(st.session_state.last_action or {'status':'Nenhuma ação executada'}); st.write('Voz:',VOICE); st.write('Modelo:',MODEL); st.write('Horário:',current_time()); st.write('Gateway:',GATEWAY_URL or 'não configurado'); st.write('Agente local:', 'configurado' if LOCAL_AGENT_TOKEN else 'não configurado')
    st.subheader('Permissões do PC'); st.table([{'Ação':a,'Nível':l} for a,l in PERMISSIONS.items()])
    if st.button('Ver log do agente local'): st.json(queue_pc_action('read_log',{'lines':25}))
    st.write('Transcrição de voz:',voice_io.status_text())
with tabs[8]:
    st.subheader('WhatsApp (V12.1)')
    st.caption('O Jarvis responde no WhatsApp pelo gateway (Render). Só números da lista autorizada são atendidos, e só mensagens com assinatura válida da Meta.')
    if st.button('Verificar agora',key='wa_check_btn'): st.session_state.wa_check=get_agent_status()
    chk=st.session_state.get('wa_check'); wa=(chk or {}).get('whatsapp') if (chk or {}).get('ok') else None
    if chk is None: st.info('Clique em "Verificar agora" para consultar o gateway.')
    elif not chk.get('ok'): st.error(chk.get('error') or 'Gateway sem resposta.')
    elif wa is None: st.warning('O gateway ainda é uma versão antiga. Faça o deploy da V12.7 no serviço do gateway.')
    else:
        (st.success if wa.get('configured') else st.warning)('WhatsApp ativo.' if wa.get('configured') else 'Faltam variáveis no gateway.')
        import whatsapp as _wa
        st.table([{'Variável (serviço do gateway)':k,'Status':'✅ definida' if k not in wa.get('missing',[]) else '❌ falta'} for k in _wa.REQUIRED])
        if wa.get('last_error'): st.error(wa['last_error'])
        if wa.get('log'): st.table(wa['log'])
    st.markdown('**URL de callback (cole no painel da Meta):**'); st.code((GATEWAY_URL or 'https://SEU-GATEWAY.onrender.com')+'/webhook')
    st.markdown('''**Passo a passo (uma vez só)**
1. Em developers.facebook.com crie um app do tipo **Business** e adicione o produto **WhatsApp**.
2. Em *WhatsApp > Configuração da API* anote o **ID do número de telefone** e adicione o seu celular como destinatário.
3. Em *Configurações do app > Básico* copie a **Chave secreta do app**. Gere um **token permanente** (Usuário do sistema) com a permissão `whatsapp_business_messaging`.
4. No Render, no serviço do **gateway**, crie: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` (um texto qualquer que você inventar), `WHATSAPP_APP_SECRET`, `WHATSAPP_ALLOWED_NUMBERS` (seu número com DDI, ex.: 5511999998888). Para o Jarvis conversar, o gateway também precisa de `OPENROUTER_API_KEY`.
5. Em *WhatsApp > Configuração > Webhook*, cole a URL acima e o mesmo `WHATSAPP_VERIFY_TOKEN`; inscreva-se no campo **messages**.
6. Mande **/ajuda** para o número de teste. Para tarefas e memória aparecerem iguais aqui e no WhatsApp, use o **mesmo Supabase** nos dois serviços.''')
with tabs[9]:
    st.subheader('Dashboard de Multiagentes (V12.7)')
    st.caption('Visão operacional da equipe: agentes disponíveis, execução recente, histórico, taxa de sucesso e etapas do Planejador.')

    last=st.session_state.get('last_team') or store.load('team_last',{})
    history=store.load('team_history',[])
    if not isinstance(history,list): history=[]

    runs=len(history)
    successful=sum(1 for x in history if x.get('ok'))
    failed=max(0,runs-successful)
    executed_steps=sum(1 for x in history for t in (x.get('trace') or []) if t.get('ok') is True)
    rate=(successful/runs*100) if runs else 0

    c1,c2,c3,c4=st.columns(4)
    c1.metric('Execuções',runs)
    c2.metric('Taxa de sucesso',f'{rate:.0f}%')
    c3.metric('Etapas concluídas',executed_steps)
    c4.metric('Execuções com falha',failed)

    st.markdown('### Agentes disponíveis')
    agent_rows=[]
    for key,v in AGENTS.items():
        uses=sum(1 for x in history for t in (x.get('trace') or []) if t.get('agente')==key)
        oks=sum(1 for x in history for t in (x.get('trace') or []) if t.get('agente')==key and t.get('ok') is True)
        agent_rows.append({'Agente':f"{v['icone']} {v['nome']}",'ID':key,'Uso':uses,'Sucesso':f"{(oks/uses*100):.0f}%" if uses else '—'})
    st.table(agent_rows)

    if last and last.get('trace'):
        st.markdown('### Última execução')
        st.write('**Objetivo:**',last.get('goal',''))
        st.write('**Status:**', 'Concluída' if last.get('ok') else 'Interrompida por falha')
        steps=last.get('trace') or []
        done=sum(1 for t in steps if t.get('ok') is True)
        st.progress((done/len(steps)) if steps else 0, text=f'{done}/{len(steps)} etapas concluídas')
        st.table([{'#':t['n'],'Agente':f"{AGENTS.get(t['agente'],{}).get('icone','')} {AGENTS.get(t['agente'],{}).get('nome',t['agente'])}",'Instrução':t['instrucao'],'Status':'⏭️ não executada' if t['ok'] is None else ('✅ ok' if t['ok'] else '❌ falhou'),'Saída':t['saida'][:300]} for t in steps])
    else:
        st.info('Nenhuma execução multiagente registrada. Use /equipe no chat.')

    st.markdown('### Histórico da equipe')
    if history:
        rows=[]
        for x in reversed(history[-15:]):
            tr=x.get('trace') or []
            rows.append({'Quando':x.get('quando','—'),'Objetivo':str(x.get('goal',''))[:90],'Etapas':len(tr),'Status':'✅ concluída' if x.get('ok') else '❌ falhou','Planejado':'Sim' if x.get('planned') else 'Fallback'})
        st.table(rows)
    else:
        st.caption('O histórico aparecerá aqui após a primeira execução.')

    with st.expander('Configuração do Planejador'):
        st.write('Máximo de etapas:',6)
        st.write('Agentes registrados:',', '.join(AGENTS.keys()))
        st.write('Regra de segurança: a equipe não apaga arquivos/pastas; exclusões continuam exigindo confirmação direta.')

    st.markdown('### Como usar')
    st.code('/equipe organize meus estudos de Python: crie a pasta Estudos e uma tarefa para amanhã às 9h')


# V12.7 — laboratório noturno + configuração remota
with tabs[11]:
    st.subheader('Laboratório Noturno')
    st.caption('Configure o loop diretamente pelo Render. O processo local lê esta configuração e executa os ciclos no seu PC.')
    cfg=get_overnight_config()
    current=cfg.get('config',{}) if cfg.get('ok') else {}
    if not current:
        current={'enabled':False,'interval_minutes':30,'start_time':'22:00','end_time':'07:00','max_cycles':0}

    st.markdown('### Controle do loop')
    c1,c2,c3,c4=st.columns(4)
    enabled= c1.toggle('Laboratório ativo',value=bool(current.get('enabled',False)),key='night_enabled')
    interval=c2.number_input('Intervalo (minutos)',min_value=1,max_value=1440,value=int(current.get('interval_minutes',30)),step=5,key='night_interval')
    start_time=c3.text_input('Início',value=str(current.get('start_time','22:00')),key='night_start',help='Formato HH:MM. Ex.: 22:00')
    end_time=c4.text_input('Fim',value=str(current.get('end_time','07:00')),key='night_end',help='Formato HH:MM. Ex.: 07:00')
    max_cycles=st.number_input('Máximo de ciclos (0 = sem limite)',min_value=0,max_value=10000,value=int(current.get('max_cycles',0)),step=1,key='night_max')
    st.caption('Exemplo: início 22:00, fim 07:00 e intervalo de 60 minutos. O horário atravessa a meia-noite normalmente.')
    if st.button('💾 Salvar configuração do laboratório',type='primary',key='save_night_config'):
        try:
            import re as _re
            if not _re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',start_time.strip()) or not _re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',end_time.strip()):
                raise ValueError('Use horários no formato HH:MM, por exemplo 22:00 e 07:00.')
            result=save_overnight_config({'enabled':enabled,'interval_minutes':int(interval),'start_time':start_time.strip(),'end_time':end_time.strip(),'max_cycles':int(max_cycles)})
            if result.get('ok'): st.success('Configuração salva no Gateway. O loop local aplicará a mudança automaticamente.')
            else: st.error(result.get('error','Não foi possível salvar.'))
        except Exception as e: st.error(str(e))

    st.markdown('### Status')
    status_cfg=get_overnight_config()
    live=status_cfg.get('config',current) if status_cfg.get('ok') else current
    a,b,c,d=st.columns(4)
    a.metric('Configuração','ATIVA' if live.get('enabled') else 'PAUSADA')
    b.metric('Intervalo',f"{live.get('interval_minutes',30)} min")
    c.metric('Janela',f"{live.get('start_time','22:00')} → {live.get('end_time','07:00')}")
    d.metric('Máx. ciclos',live.get('max_cycles',0) or '∞')

    from pathlib import Path as _NightPath
    _lab=_NightPath(__file__).resolve().parent/'overnight_workspace'; _state=_lab/'state.json'
    try: _ns=json.loads(_state.read_text(encoding='utf-8')) if _state.exists() else {}
    except Exception: _ns={}
    _hist=_ns.get('history',[]) if isinstance(_ns.get('history',[]),list) else []
    _running=_ns.get('status')=='running'
    a,b,c,d=st.columns(4)
    a.metric('Processo local','RODANDO' if _running else (_ns.get('status') or 'parado'))
    b.metric('Ciclos executados',_ns.get('cycle',0))
    last=_hist[-1] if _hist else {}
    c.metric('Testes','OK' if last.get('tests_ok') else ('FALHA' if last else '—'))
    d.metric('Sintaxe','OK' if last.get('compile_ok') else ('FALHA' if last else '—'))

    st.markdown('### Agentes do laboratório')
    try:
        from overnight_agents import ROLES
        st.table([{'Agente':k.replace('_',' ').title(),'Função':v} for k,v in ROLES.items()])
    except Exception as e: st.warning(f'Não foi possível carregar os agentes: {e}')
    if _hist:
        st.markdown('### Últimos ciclos'); st.table(list(reversed(_hist[-12:])))
    reports=sorted((_lab/'reports').glob('cycle_*.json'),reverse=True) if (_lab/'reports').exists() else []
    if reports:
        st.markdown('### Último relatório')
        try:
            _rep=json.loads(reports[0].read_text(encoding='utf-8'))
            st.write('**Ciclo:**',_rep.get('cycle'),'• **Data:**',_rep.get('timestamp'))
            st.write('**Qualidade:**'); st.write(_rep.get('quality',''))
            st.write('**Segurança:**'); st.write(_rep.get('security',''))
            st.write('**Red Team defensivo:**'); st.write(_rep.get('red_team',''))
            st.write('**Melhorias propostas:**'); st.write(_rep.get('improvements',''))
            with st.expander('Exemplos encontrados na web'): st.json(_rep.get('web_examples',[]))
        except Exception as e: st.error(f'Erro ao ler relatório: {e}')
    st.info('Você precisa deixar o processo local do laboratório iniciado uma vez no PC. Depois disso, horários, intervalo, ativação e limite de ciclos podem ser alterados por esta tela, sem voltar ao CMD.')

with tabs[10]:
    st.subheader('Tools 2.0')
    st.caption('Catálogo central de ferramentas. A execução continua sujeita às permissões e aos agentes autorizados.')
    import tool_registry as _tr
    rows=_tr.tool_rows()
    c1,c2,c3=st.columns(3)
    c1.metric('Tools',len(rows))
    c2.metric('Categorias',len(set(r['Categoria'] for r in rows)))
    c3.metric('Agentes com tools',len(set(a for r in rows for a in r['Agentes'].split(', '))))
    st.table(rows)
    st.markdown('### Tools por agente')
    for aid,av in AGENTS.items():
        tools=tools_for_agent(aid)
        with st.expander(f"{av['icone']} {av['nome']} — {len(tools)} tool(s)"):
            if not tools:
                st.info('Nenhuma tool registrada.')
            else:
                st.table([{'ID':k,'Nome':v['nome'],'Categoria':v['categoria'],'Risco':v['risco']} for k,v in tools.items()])
    st.info('V12.8: Computer Agent poderá usar este catálogo como camada de descoberta, mantendo as permissões atuais.')


# V12.8 — Computer Agent
with tabs[12]:
    st.subheader('Computer Agent')
    st.caption('Planeja, executa e verifica sequências de ações seguras no seu PC. Ações destrutivas continuam bloqueadas.')

    try:
        from computer_agent import plan_instruction, execute as execute_computer
        import computer_agent as _ca
    except Exception as e:
        st.error(f'Computer Agent indisponível: {e}')
    else:
        c1,c2,c3=st.columns(3)
        c1.metric('Modo','Seguro')
        c2.metric('Ações permitidas',len(_ca.SAFE_ACTIONS))
        c3.metric('Ações bloqueadas',len(_ca.BLOCKED_ACTIONS))

        instruction=st.text_area('O que o Computer Agent deve fazer?', placeholder='Ex.: crie a pasta ProjetoTeste e depois crie o arquivo README.txt dentro dela', height=100, key='computer_instruction')
        instruction_text = instruction if isinstance(instruction, str) else ''
        if instruction_text.strip():
            plan, plan_error=plan_instruction(instruction_text)
            st.markdown('### Plano detectado')
            if plan:
                st.table([{'#':i+1,'Ação':a,'Parâmetros':json.dumps(p,ensure_ascii=False)} for i,(a,p) in enumerate(plan)])
            else:
                st.warning(plan_error)

        run=st.button('▶️ Executar Computer Agent',type='primary',disabled=not bool(instruction_text.strip()),key='run_computer_agent')
        if run:
            if not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
                st.error('Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN no Render.')
            else:
                with st.spinner('Computer Agent executando e verificando as etapas...'):
                    result=execute_computer(instruction_text, queue_pc_action)
                st.session_state['computer_last']=result
                if result.get('ok'): st.success(result.get('summary','Execução concluída.'))
                else: st.error(result.get('error','Execução interrompida.'))

        last_ca=st.session_state.get('computer_last')
        if last_ca:
            st.markdown('### Última execução')
            for item in last_ca.get('trace',[]):
                status='✅' if item.get('ok') else '❌'
                with st.expander(f"{status} Etapa {item.get('step')}: {item.get('description','')}", expanded=not item.get('ok',False)):
                    st.write('**Verificação:**', item.get('verification',{}).get('detalhe','—'))
                    st.json(item.get('result',{}))

        history=store.load('computer_agent_history',[])
        if isinstance(history,list) and history:
            st.markdown('### Histórico do Computer Agent')
            rows=[]
            for h in reversed(history[-15:]):
                rows.append({'Instrução':str(h.get('instrucao',''))[:100],'Status':'✅' if h.get('ok') else '❌','Etapas':len(h.get('trace') or [])})
            st.table(rows)

        st.info('Segurança: o Computer Agent não usa shell arbitrário e não pode apagar arquivos. Ele só usa ações já permitidas pelo agente local.')


# V12.9 — Security & Permissions
with tabs[13]:
    st.subheader('Security & Permissions')
    st.caption('Camada central que decide risco, aprovação, limites e auditoria antes das ações do Jarvis.')
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
        st.warning('Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN para usar a segurança central.')
    else:
        ss=get_security_status(); approvals=get_security_approvals()
        pol=ss.get('policy',{}) if isinstance(ss,dict) else {}
        kill=bool(ss.get('kill_switch'))
        c1,c2,c3,c4=st.columns(4)
        c1.metric('Estado','BLOQUEADO' if kill else 'ATIVO')
        c2.metric('Aprovações pendentes',ss.get('pending',0))
        c3.metric('Auditoria',ss.get('audit_entries',0))
        c4.metric('Limite/ciclo',pol.get('max_actions_per_cycle',20))
        st.markdown('### Kill Switch')
        st.write('Bloqueia imediatamente novas ações do gateway e cancela aprovações pendentes.')
        if kill:
            if st.button('Desativar Kill Switch',type='primary',key='security_unkill'):
                security_kill(False); st.rerun()
        else:
            if st.button('Ativar Kill Switch',key='security_kill'):
                security_kill(True); st.rerun()

        st.markdown('### Matriz de risco')
        try:
            import security as _sec
            rows=[{'Ação':a,'Risco':_sec.risk_for(a),'Aprovação':'Sim' if _sec.needs_approval(a) else 'Não','Estado':'Bloqueada' if _sec.blocked(a) else 'Permitida'} for a in sorted(_sec.RISK)]
            st.table(rows)
        except Exception: pass

        st.markdown('### Aprovações')
        pending=[x for x in approvals if x.get('status')=='pending']
        if pending:
            for item in pending:
                with st.container(border=True):
                    st.write(f"**{item.get('action')}** • risco **{item.get('risk')}** • agente: {item.get('agent')}" )
                    st.json(item.get('params',{}))
                    a,b=st.columns(2)
                    if a.button('Aprovar',key='approve_'+item['id'],type='primary'):
                        out=security_decide(item['id'],'approve')
                        if out.get('ok'): st.success('Ação aprovada e colocada na fila.')
                        else: st.error(out.get('error','Falha ao aprovar.'))
                        st.rerun()
                    if b.button('Negar',key='deny_'+item['id']):
                        out=security_decide(item['id'],'deny')
                        st.rerun()
        else:
            st.info('Nenhuma ação aguardando aprovação.')

        st.markdown('### Limites')
        with st.form('security_limits'):
            max_cycle=st.number_input('Máximo de ações por ciclo',1,100,int(pol.get('max_actions_per_cycle',20)))
            max_agent=st.number_input('Máximo de ações por agente',1,50,int(pol.get('max_actions_per_agent',10)))
            save=st.form_submit_button('Salvar limites')
            if save:
                out=security_policy_save({'max_actions_per_cycle':int(max_cycle),'max_actions_per_agent':int(max_agent)})
                st.success('Política salva.' if out.get('ok') else out.get('error','Falha ao salvar.'))

        st.markdown('### Auditoria recente')
        try:
            ar=requests.get(f'{GATEWAY_URL}/security/audit',headers={'X-Agent-Token':LOCAL_AGENT_TOKEN},timeout=6).json().get('audit',[])
            if ar: st.table([{'Hora':x.get('timestamp','')[:19].replace('T',' '),'Evento':x.get('event'),'Ação':x.get('action','—'),'Risco':x.get('risk','—'),'Agente':x.get('agent','—')} for x in reversed(ar[-20:])])
            else: st.info('Nenhum evento registrado ainda.')
        except Exception as e: st.warning(f'Auditoria indisponível: {e}')

        st.info('Regra V12.9: baixo risco pode executar automaticamente; médio/alto risco entra na fila de aprovação; ações bloqueadas continuam bloqueadas. O Laboratório Noturno pode analisar segurança, mas não recebe permissão para aplicar mudanças sozinho.')


# V13.1 — Dashboard 2.0 / Command Center
with tabs[14]:
    st.subheader('Command Center — Dashboard 2.0')
    st.caption('Visão operacional central do Jarvis: estado, execução, dispositivos, missões e timeline.')

    try:
        _agent = get_agent_status()
    except Exception:
        _agent = {'ok': False, 'online': False, 'info': {}}
    try:
        _sec = get_security_status()
    except Exception:
        _sec = {}
    try:
        _wa = get_agent_status().get('whatsapp', {}) if isinstance(get_agent_status(), dict) else {}
    except Exception:
        _wa = {}

    _devices = devices.list_devices()
    _missions = orchestrator.list_missions()
    _events = orchestrator.events()
    _running = [m for m in _missions if m.get('status') == 'running']
    _failed = [m for m in _missions if m.get('status') == 'failed']

    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric('Versão', '13.2.0')
    c2.metric('Agente local', 'ONLINE' if _agent.get('online') else 'OFFLINE')
    c3.metric('Dispositivos', len(_devices))
    c4.metric('Missões ativas', len(_running))
    c5.metric('Eventos', len(_events))

    st.markdown('### Estado do sistema')
    a,b,c,d=st.columns(4)
    a.markdown('<div class="jarvis-card"><div class="jarvis-label">Core</div><div class="jarvis-value jarvis-ok">OPERACIONAL</div><div>Planner, memória, tasks e tools integrados.</div></div>', unsafe_allow_html=True)
    sec_class = 'jarvis-bad' if _sec.get('kill_switch') else 'jarvis-ok'
    sec_label = 'BLOQUEADO' if _sec.get('kill_switch') else 'ATIVA'
    b.markdown(f'<div class="jarvis-card"><div class="jarvis-label">Segurança</div><div class="jarvis-value {sec_class}">{sec_label}</div><div>{_sec.get("pending",0)} aprovação(ões) pendente(s).</div></div>', unsafe_allow_html=True)
    c.markdown(f'<div class="jarvis-card"><div class="jarvis-label">Missões</div><div class="jarvis-value">{len(_missions)}</div><div>{len(_running)} em execução • {len(_failed)} falharam.</div></div>', unsafe_allow_html=True)
    online_devices = len([x for x in _devices if x.get('status') == 'online'])
    d.markdown(f'<div class="jarvis-card"><div class="jarvis-label">Dispositivos</div><div class="jarvis-value">{online_devices}/{len(_devices)}</div><div>online / cadastrados.</div></div>', unsafe_allow_html=True)

    st.markdown('### Fluxo de execução')
    st.code('OBJETIVO  →  PLANNER  →  AGENTES  →  TOOLS/SKILLS  →  SEGURANÇA  →  LOCAL AGENT  →  QA/VERIFICAÇÃO  →  RESULTADO', language='text')

    left,right=st.columns([1,1])
    with left:
        st.markdown('### Componentes')
        st.table([{'ID':k,'Componente':v} for k,v in orchestrator.COMPONENTS.items()])
    with right:
        st.markdown('### Capacidades')
        cap=orchestrator.capabilities()
        for key,value in cap.items():
            if key != 'version':
                st.write(f'**{key.replace("_"," ").title()}**: {", ".join(value) if isinstance(value,list) else value}')

    st.markdown('### Dispositivos conectados')
    if _devices:
        rows=[]
        for x in _devices:
            status=str(x.get('status','offline')).upper()
            rows.append({'Status':status,'Nome':x.get('name','—'),'ID':x.get('id','—'),'Versão':x.get('version','—'),'Último contato':str(x.get('last_seen','—'))[:19].replace('T',' ')})
        st.table(rows)
    else:
        st.info('Nenhum dispositivo registrado. A base Multi-PC já está preparada para a próxima etapa.')

    st.markdown('### Missões')
    if _missions:
        st.table([{'ID':x.get('id','—'),'Objetivo':str(x.get('goal',''))[:110],'Status':x.get('status','—'),'Origem':x.get('source','—'),'Atualizada':str(x.get('updated_at',''))[:19].replace('T',' ')} for x in reversed(_missions[-15:])])
    else:
        st.caption('Nenhuma missão registrada ainda.')

    st.markdown('### Timeline global')
    if _events:
        rows=[]
        for x in reversed(_events[-25:]):
            rows.append({'Hora':str(x.get('timestamp',''))[:19].replace('T',' '),'Origem':x.get('source','—'),'Evento':x.get('event','—'),'Status':x.get('status','—'),'Detalhes':json.dumps(x.get('data',{}),ensure_ascii=False)[:220]})
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption('A timeline aparecerá conforme o Jarvis executar ações.')

    with st.expander('Arquitetura do Dashboard 2.0'):
        st.write('O Dashboard 2.0 é uma camada visual. Ele não concede novas permissões aos agentes e não bypassa o Permission Manager.')
        st.write('Próxima etapa: V13.2 — Agent Map, com visualização do fluxo Planner → Agentes → QA em tempo real.')

    st.info('V13.1 adiciona a nova camada visual sem alterar a política de segurança da V12.9/V13.0.')


# V13.2 — Agent Map
with tabs[15]:
    st.subheader('Agent Map — V13.2')
    st.caption('Mapa operacional do fluxo Planner → Agentes → QA/Verificação. A visualização usa o estado real das missões e da timeline; não concede permissões novas.')

    try:
        _missions = orchestrator.list_missions()
    except Exception:
        _missions = []
    try:
        _events = orchestrator.events()
    except Exception:
        _events = []

    _running = [m for m in _missions if m.get('status') == 'running']
    _failed = [m for m in _missions if m.get('status') == 'failed']
    _done = [m for m in _missions if m.get('status') in ('done','completed','success')]

    c1,c2,c3,c4=st.columns(4)
    c1.metric('Missões em execução', len(_running))
    c2.metric('Concluídas', len(_done))
    c3.metric('Falhas', len(_failed))
    c4.metric('Eventos', len(_events))

    # Descobre agentes citados nos eventos/missões sem confiar em nomes fixos.
    _agent_names=[]
    for ev in _events[-100:]:
        data=ev.get('data',{}) if isinstance(ev.get('data',{}),dict) else {}
        for key in ('agent','agent_id','executor','worker'):
            value=data.get(key) or ev.get(key)
            if value and str(value) not in _agent_names:
                _agent_names.append(str(value))
    for m in _missions[-50:]:
        for key in ('agent','agent_id','executor'):
            value=m.get(key)
            if value and str(value) not in _agent_names:
                _agent_names.append(str(value))
    if not _agent_names:
        _agent_names=list(AGENTS.keys())
    _agent_names=_agent_names[:12]

    def _agent_state(name):
        lname=str(name).lower()
        for ev in reversed(_events[-100:]):
            data=ev.get('data',{}) if isinstance(ev.get('data',{}),dict) else {}
            candidate=str(data.get('agent') or data.get('agent_id') or ev.get('agent') or '').lower()
            if candidate == lname or lname in candidate or candidate in lname:
                status=str(ev.get('status') or data.get('status') or '').lower()
                if status in ('running','executing','active'):
                    return 'EXECUTANDO','jarvis-node-running'
                if status in ('error','failed','failure'):
                    return 'ERRO','jarvis-node-error'
                if status in ('done','completed','success','ok'):
                    return 'OK','jarvis-node-ok'
        return 'AGUARDANDO','jarvis-node-idle'

    st.markdown('### Fluxo em tempo real')
    _nodes=[]
    for title,state,cls in [
        ('OBJETIVO','ENTRADA','jarvis-node-ok'),
        ('PLANNER','ORQUESTRANDO','jarvis-node-running' if _running else 'jarvis-node-idle')]:
        _nodes.append(f'<div class="jarvis-node {cls}"><div class="jarvis-node-title">{title}</div><div class="jarvis-node-state">{state}</div></div>')
    for name in _agent_names:
        state,cls=_agent_state(name)
        _nodes.append(f'<div class="jarvis-node {cls}"><div class="jarvis-node-title">{name}</div><div class="jarvis-node-state">{state}</div></div>')
    _nodes.append('<div class="jarvis-node jarvis-node-idle"><div class="jarvis-node-title">QA / VERIFICAÇÃO</div><div class="jarvis-node-state">PÓS-EXECUÇÃO</div></div>')
    _nodes.append('<div class="jarvis-node jarvis-node-ok"><div class="jarvis-node-title">RESULTADO</div><div class="jarvis-node-state">ENTREGA</div></div>')

    _html='<div class="jarvis-map">' + ''.join(_nodes) + '</div>'
    st.markdown(_html, unsafe_allow_html=True)

    st.markdown('### Agentes detectados')
    _rows=[]
    for name in _agent_names:
        state,_=_agent_state(name)
        _rows.append({'Agente':name,'Estado':state})
    st.dataframe(_rows,use_container_width=True,hide_index=True)

    st.markdown('### Última atividade por agente')
    _latest=[]
    for name in _agent_names:
        match=None
        lname=str(name).lower()
        for ev in reversed(_events[-150:]):
            data=ev.get('data',{}) if isinstance(ev.get('data',{}),dict) else {}
            candidate=str(data.get('agent') or data.get('agent_id') or ev.get('agent') or '').lower()
            if candidate == lname or lname in candidate or candidate in lname:
                match=ev; break
        if match:
            _latest.append({'Agente':name,'Evento':match.get('event','—'),'Status':match.get('status','—'),'Hora':str(match.get('timestamp',''))[:19].replace('T',' ')})
    if _latest:
        st.dataframe(_latest,use_container_width=True,hide_index=True)
    else:
        st.info('Ainda não há eventos de agentes suficientes para preencher o mapa. Execute uma missão para visualizar o fluxo real.')

    st.markdown('### Missões recentes')
    if _missions:
        st.dataframe([
            {'ID':m.get('id','—'),'Objetivo':str(m.get('goal',''))[:120],'Status':m.get('status','—'),'Etapas':len(m.get('steps') or m.get('plan') or [])}
            for m in reversed(_missions[-12:])
        ],use_container_width=True,hide_index=True)
    else:
        st.caption('Nenhuma missão registrada.')

    with st.expander('Como o mapa funciona'):
        st.write('O mapa é uma camada de observabilidade. Ele lê missões e eventos registrados pelo Core e apresenta o estado conhecido dos agentes. Ele não executa comandos diretamente e não altera permissões.')
        st.write('Próxima evolução: V13.3 — Live Operations, com acompanhamento mais detalhado da ação atual, ferramenta, duração e resultado.')

    st.info('V13.2 adiciona visualização operacional sem bypassar o Permission Manager.')
