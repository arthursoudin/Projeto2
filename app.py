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

DEFAULTS={'messages':[],'tasks':[],'memory':{},'last_action':None,'session_id':uuid.uuid4().hex,'honcho_status':'não configurado','honcho_context':'','pending_pc':None}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k]=v

def load_json(path,default):
    try: return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    except Exception: return default

def save_json(path,data):
    try: path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); return True
    except Exception: return False
if not st.session_state.memory: st.session_state.memory=load_json(MEMORY_FILE,{})
if not st.session_state.tasks: st.session_state.tasks=load_json(TASKS_FILE,[])

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

SKILLS={
'planejamento':{'description':'Transforma objetivos em planos e passos executáveis.','keywords':['planejar','plano','organizar','objetivo','projeto']},
'tarefas':{'description':'Cria, consulta e acompanha tarefas.','keywords':['tarefa','todo','fazer','lembrete','pendência','prazo']},
'memoria':{'description':'Salva e recupera contexto entre conversas.','keywords':['lembre','lembrar','guarde','memória','recorde','você lembra']},
'web':{'description':'Pesquisa informações públicas na web.','keywords':['pesquise','pesquisar','internet','web','site','notícia']},
'programacao':{'description':'Ajuda com Python, Java, JavaScript, HTML, CSS e arquitetura.','keywords':['python','java','javascript','html','css','código','programação']},
'postgresql':{'description':'Ajuda com SQL e PostgreSQL.','keywords':['sql','postgres','postgresql','banco de dados','database']}}
def detect_skills(text):
    low=text.lower(); found=[n for n,s in SKILLS.items() if any(k in low for k in s['keywords'])]; return found or ['planejamento']

def now(): return dt.datetime.now().astimezone()
def current_time(): return now().strftime('%d/%m/%Y %H:%M:%S')
def iso_now(): return now().isoformat(timespec='seconds')

def calculator(expr):
    if not expr or any(c not in '0123456789+-*/().,% ' for c in expr): return 'Expressão não permitida.'
    try: return str(eval(expr.replace('%','/100'),{'__builtins__':{}},{}))
    except Exception as e: return f'Erro no cálculo: {e}'

def parse_due(text):
    """Extrai datas/horários simples em PT-BR. Retorna ISO local ou vazio."""
    s=text.lower()
    base=now()
    hour=None
    m=re.search(r'\b(?:às|as|a)\s*(\d{1,2})(?:[:h](\d{2}))?\b',s)
    if m: hour=(int(m.group(1)),int(m.group(2) or 0))
    if 'hoje' in s: d=base.date()
    elif 'amanhã' in s or 'amanha' in s: d=(base+dt.timedelta(days=1)).date()
    elif 'depois de amanhã' in s or 'depois de amanha' in s: d=(base+dt.timedelta(days=2)).date()
    else:
        m=re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b',s)
        if m:
            y=int(m.group(3) or base.year); y += 2000 if y < 100 else 0
            try: d=dt.date(y,int(m.group(2)),int(m.group(1)))
            except ValueError: d=None
        else: d=None
    if d is None: return ''
    h,mi=hour or (9,0)
    return dt.datetime.combine(d,dt.time(h,mi)).astimezone().isoformat(timespec='minutes')

def recurrence_from_text(text):
    s=text.lower()
    if 'todo dia' in s or 'diariamente' in s: return 'daily'
    if 'todo sábado' in s or 'todo sabado' in s: return 'weekly:saturday'
    if 'todo domingo' in s: return 'weekly:sunday'
    if 'toda segunda' in s or 'toda segunda-feira' in s: return 'weekly:monday'
    if 'toda terça' in s or 'toda terca' in s: return 'weekly:tuesday'
    if 'toda quarta' in s: return 'weekly:wednesday'
    if 'toda quinta' in s: return 'weekly:thursday'
    if 'toda sexta' in s: return 'weekly:friday'
    return ''

def clean_task_text(text):
    c=text.strip()
    patterns=['crie uma tarefa','adiciona uma tarefa','adicione uma tarefa','nova tarefa','criar tarefa','me lembre de','lembre de']
    for p in patterns: c=re.sub(re.escape(p), '', c, flags=re.I)
    c=re.sub(r'\b(?:hoje|amanhã|amanha|depois de amanhã|depois de amanha)\b','',c,flags=re.I)
    c=re.sub(r'\b(?:às|as|a)\s*\d{1,2}(?:[:h]\d{2})?\b','',c,flags=re.I)
    c=re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b','',c)
    return re.sub(r'\s+',' ',c).strip(' .,-') or 'Tarefa sem título'

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
    return '''Você é Jarvis, assistente pessoal em português do Brasil. Seja direto, inteligente, útil e honesto. Use memória e tarefas como contexto, sem inventar fatos. Se algo estiver incerto, diga isso. Quando uma ferramenta já tiver executado uma ação, explique o resultado sem fingir que fará outra ação.\nSkills: %s\nControle local do PC: somente por agente autorizado e ações permitidas. Só diga que algo foi feito se o resultado da ferramenta tiver ok=true; se houver erro, explique o erro e como resolver. Se estiver AGUARDANDO CONFIRMAÇÃO, nada foi executado ainda.\nMemória local: %s\nTarefas: %s\nResumo de tarefas: %s\nMemória Honcho recuperada: %s''' % (json.dumps(list(SKILLS),ensure_ascii=False),json.dumps(st.session_state.memory,ensure_ascii=False),json.dumps(st.session_state.tasks,ensure_ascii=False),json.dumps(task_summary(),ensure_ascii=False),memory_context or 'nenhuma')

def ask_llm(user_text,tool_result=None,memory_context=''):
    if not client: return 'OPENROUTER_API_KEY não configurada.'
    msgs=[{'role':'system','content':system_prompt(memory_context)}]+st.session_state.messages[-12:]
    if tool_result: msgs.append({'role':'system','content':f'Resultado da ferramenta executada: {tool_result}'})
    msgs.append({'role':'user','content':user_text})
    r=client.chat.completions.create(model=MODEL,messages=msgs,temperature=0.4); return r.choices[0].message.content

async def make_audio(text,filename):
    await edge_tts.Communicate(text=str(text),voice=VOICE,rate=VOICE_RATE,pitch=VOICE_PITCH).save(filename); return filename

GATEWAY_URL=os.getenv('JARVIS_GATEWAY_URL','').rstrip('/')
LOCAL_AGENT_TOKEN=os.getenv('LOCAL_AGENT_TOKEN','')

def queue_pc_action(action, params=None, wait_seconds=15):
    """Envia a ação ao agente local e aguarda o resultado real."""
    if not GATEWAY_URL or not LOCAL_AGENT_TOKEN:
        return {'ok':False,'error':'Configure JARVIS_GATEWAY_URL e LOCAL_AGENT_TOKEN no Render.'}
    if not requests:
        return {'ok':False,'error':'requests não está disponível.'}
    headers={'X-Agent-Token':LOCAL_AGENT_TOKEN}
    try:
        r=requests.post(f'{GATEWAY_URL}/agent/commands', json={'action':action,'params':params or {}}, headers=headers, timeout=10)
        r.raise_for_status(); queued=r.json()
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

def run_pc_plan(steps, confirmed=False):
    """Executa os passos em ordem. Ações sensíveis esperam confirmação. Para no primeiro erro."""
    done=[]
    for i,(action,params) in enumerate(steps):
        if action in CONFIRM_ACTIONS and not confirmed:
            st.session_state.pending_pc=steps[i:]
            return done,'confirm'
        p=dict(params)
        if action in CONFIRM_ACTIONS: p['confirmed']=True
        r=queue_pc_action(action,p)
        done.append({'acao':describe_step(action,params),'ok':r.get('ok'),'resultado':r.get('result') or r.get('error')})
        if not r.get('ok'): return done,'error'
    return done,'ok'

def save_memory_item(key,value):
    st.session_state.memory[str(key)]=str(value)
    save_json(MEMORY_FILE,st.session_state.memory)
    return f'Memória local salva: {value}'

st.set_page_config(page_title='Jarvis V11',page_icon='J',layout='wide')
st.title('Jarvis V11.9'); st.caption('Agente pessoal • Memória • Tarefas • PC: arquivos, apps, navegador, comandos compostos • Permissões • Voz')
with st.sidebar:
    st.header('Sistema'); st.metric('Modelo',MODEL.split('/')[-1][:24]); st.metric('Skills',len(SKILLS)); st.metric('Tarefas',len(st.session_state.tasks)); st.metric('Pendentes',task_summary()['pendentes']); st.metric('Memórias locais',len(st.session_state.memory)); st.write('**PC Agent:**', 'configurado' if (GATEWAY_URL and LOCAL_AGENT_TOKEN) else 'não configurado')
    st.write('**Honcho:**',st.session_state.honcho_status)
    if HONCHO_API_KEY: st.success('HONCHO_API_KEY configurada')
    else: st.warning('HONCHO_API_KEY não configurada')
    if st.button('Nova conversa'): st.session_state.messages=[]; st.session_state.session_id=uuid.uuid4().hex; st.rerun()

tabs=st.tabs(['Chat','Tarefas','Automações','Memória','Honcho','Skills','Sistema'])
with tabs[0]:
    for m in st.session_state.messages:
        with st.chat_message(m['role']): st.markdown(m['content'])
    prompt=st.chat_input('Fale com o Jarvis...')
    if prompt:
        st.session_state.messages.append({'role':'user','content':prompt})
        with st.chat_message('user'): st.markdown(prompt)
        skills=detect_skills(prompt); tool=None; result=None; confirm_note=''
        pending=st.session_state.pending_pc
        if pending:
            st.session_state.pending_pc=None
            if is_confirm(prompt):
                done,status=run_pc_plan(pending,confirmed=True); tool='computer'; result=json.dumps({'confirmado':True,'acoes':done,'status':status},ensure_ascii=False)
            elif is_cancel(prompt):
                tool='computer'; result='O usuário cancelou a ação pendente. Nada foi executado.'
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
                answer=ask_llm(prompt,result,context)+confirm_note; st.markdown(answer); st.session_state.messages.append({'role':'assistant','content':answer}); honcho_save_turn(prompt,answer)
                try: asyncio.run(make_audio(answer,'/tmp/jarvis_v10.mp3')); st.audio('/tmp/jarvis_v10.mp3',format='audio/mp3',autoplay=True)
                except Exception as e: st.caption(f'Áudio indisponível: {e}')
            except Exception as e: st.error(f'Erro no Jarvis: {e}')
with tabs[1]:
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
with tabs[2]:
    st.subheader('Automações')
    st.write('A V10 registra prazos e recorrências e verifica tarefas vencidas quando o Jarvis é acessado. Em Render, a execução em segundo plano contínua depende de um scheduler externo; esta base prepara as regras sem fingir que existe um cron persistente.')
    pending=[t for t in st.session_state.tasks if t.get('status')!='done']
    if pending:
        for t in pending:
            status=task_status_text(t); label='Atrasada' if status=='atrasada' else 'Agendada' if t.get('due_at') else 'Sem horário'
            st.write(f"Tarefa #{t['id']} — {t['text']} — {label}")
    else: st.info('Nenhuma automação/tarefa pendente.')
with tabs[3]:
    st.subheader('Memória local de fallback'); st.json(st.session_state.memory) if st.session_state.memory else st.info('Nenhuma memória local salva.')
with tabs[4]:
    st.subheader('Memória Honcho'); st.write('Workspace:',HONCHO_WORKSPACE); st.write('Peer:',HONCHO_USER_ID); st.write('Sessão:',st.session_state.session_id); st.write('Status:',st.session_state.honcho_status)
    if st.button('Testar memória Honcho'):
        c=honcho_context('Quais informações importantes você tem sobre este usuário?'); st.session_state.honcho_context=c
        if c: st.success('Memória recuperada.'); st.code(c[:12000])
        else: st.warning('Não foi possível recuperar memória. Verifique HONCHO_API_KEY.')
with tabs[5]:
    for n,s in SKILLS.items():
        with st.expander(n): st.write(s['description']); st.write(', '.join(s['keywords']))
with tabs[6]:
    st.json(st.session_state.last_action or {'status':'Nenhuma ação executada'}); st.write('Voz:',VOICE); st.write('Modelo:',MODEL); st.write('Horário:',current_time()); st.write('Gateway:',GATEWAY_URL or 'não configurado'); st.write('Agente local:', 'configurado' if LOCAL_AGENT_TOKEN else 'não configurado')
    st.subheader('Permissões do PC'); st.table([{'Ação':a,'Nível':l} for a,l in PERMISSIONS.items()])
    if st.button('Ver log do agente local'): st.json(queue_pc_action('read_log',{'lines':25}))
