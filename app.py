import os, json, asyncio, datetime as dt, uuid
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

MODEL=os.getenv('OPENROUTER_MODEL','meta-llama/llama-3.3-70b-instruct:free')
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

for k,v in {'messages':[],'tasks':[],'memory':{},'last_action':None,'session_id':uuid.uuid4().hex,'honcho_status':'não configurado','honcho_context':''}.items():
    if k not in st.session_state: st.session_state[k]=v

def load_json(path,default):
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
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
'tarefas':{'description':'Cria e consulta tarefas.','keywords':['tarefa','todo','fazer','lembrete','pendência']},
'memoria':{'description':'Salva e recupera contexto entre conversas.','keywords':['lembre','lembrar','guarde','memória','recorde','você lembra']},
'web':{'description':'Pesquisa informações públicas na web.','keywords':['pesquise','pesquisar','internet','web','site','notícia']},
'programacao':{'description':'Ajuda com Python, Java, JavaScript, HTML, CSS e arquitetura.','keywords':['python','java','javascript','html','css','código','programação']},
'postgresql':{'description':'Ajuda com SQL e PostgreSQL.','keywords':['sql','postgres','postgresql','banco de dados','database']}}
def detect_skills(text):
    low=text.lower(); found=[n for n,s in SKILLS.items() if any(k in low for k in s['keywords'])]; return found or ['planejamento']

def current_time(): return dt.datetime.now().astimezone().strftime('%d/%m/%Y %H:%M:%S')
def calculator(expr):
    if not expr or any(c not in '0123456789+-*/().,% ' for c in expr): return 'Expressão não permitida.'
    try: return str(eval(expr.replace('%','/100'),{'__builtins__':{}},{}))
    except Exception as e: return f'Erro no cálculo: {e}'
def create_task(text):
    t={'id':len(st.session_state.tasks)+1,'text':text.strip(),'done':False,'created_at':current_time()}; st.session_state.tasks.append(t); save_json(TASKS_FILE,st.session_state.tasks); return t
def save_memory_item(key,value): st.session_state.memory[key]=value; save_json(MEMORY_FILE,st.session_state.memory); return f'Memória local salva: {key} = {value}'
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
    if any(x in l for x in ['que horas','horário','data de hoje']): return 'time'
    if any(x in l for x in ['crie uma tarefa','adiciona uma tarefa','nova tarefa']): return 'task'
    if any(x in l for x in ['lembre de','lembra de','guarde que','memorize']): return 'memory'
    if any(x in l for x in ['pesquise','procure na internet','pesquisa na web']): return 'web'
    if any(x in l for x in ['busque na memória','procure na memória','o que você lembra','você lembra']): return 'memory_search'
    return None
def execute_tool(text):
    tool=choose_tool(text)
    if tool=='calculator':
        e=text.lower()
        for p in ['quanto é','calcule','calcular']: e=e.replace(p,'')
        return tool,calculator(e.strip())
    if tool=='time': return tool,current_time()
    if tool=='task':
        c=text
        for p in ['crie uma tarefa','adiciona uma tarefa','nova tarefa']: c=c.lower().replace(p,'',1)
        t=create_task(c.strip()); return tool,f"Tarefa #{t['id']} criada: {t['text']}"
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
    return '''Você é Jarvis, assistente pessoal em português do Brasil. Seja direto, inteligente, útil e honesto. Use a memória como contexto, sem inventar fatos. Se algo estiver incerto, diga isso.\nSkills: %s\nMemória local: %s\nTarefas: %s\nMemória Honcho recuperada: %s''' % (json.dumps(list(SKILLS),ensure_ascii=False),json.dumps(st.session_state.memory,ensure_ascii=False),json.dumps(st.session_state.tasks,ensure_ascii=False),memory_context or 'nenhuma')
def ask_llm(user_text,tool_result=None,memory_context=''):
    if not client: return 'OPENROUTER_API_KEY não configurada.'
    msgs=[{'role':'system','content':system_prompt(memory_context)}]+st.session_state.messages[-12:]
    if tool_result: msgs.append({'role':'system','content':f'Resultado da ferramenta: {tool_result}'})
    msgs.append({'role':'user','content':user_text})
    r=client.chat.completions.create(model=MODEL,messages=msgs,temperature=0.4); return r.choices[0].message.content
async def make_audio(text,filename): await edge_tts.Communicate(text=str(text),voice=VOICE,rate=VOICE_RATE,pitch=VOICE_PITCH).save(filename); return filename

st.set_page_config(page_title='Jarvis V9',page_icon='🤖',layout='wide')
st.title('🤖 Jarvis V9'); st.caption('Agente pessoal • Honcho Memory • Skills • Tools • Web • Edge TTS')
with st.sidebar:
    st.header('Sistema'); st.metric('Modelo',MODEL.split('/')[-1][:24]); st.metric('Skills',len(SKILLS)); st.metric('Tarefas',len(st.session_state.tasks)); st.metric('Memórias locais',len(st.session_state.memory))
    st.write('**Honcho:**',st.session_state.honcho_status)
    if HONCHO_API_KEY: st.success('HONCHO_API_KEY configurada')
    else: st.warning('HONCHO_API_KEY não configurada')
    if st.button('Nova conversa'): st.session_state.messages=[]; st.session_state.session_id=uuid.uuid4().hex; st.rerun()

tabs=st.tabs(['Chat','Tarefas','Memória','Honcho','Skills','Sistema'])
with tabs[0]:
    for m in st.session_state.messages:
        with st.chat_message(m['role']): st.markdown(m['content'])
    prompt=st.chat_input('Fale com o Jarvis...')
    if prompt:
        st.session_state.messages.append({'role':'user','content':prompt})
        with st.chat_message('user'): st.markdown(prompt)
        skills=detect_skills(prompt); tool,result=execute_tool(prompt); context=honcho_context(prompt); st.session_state.honcho_context=context
        st.session_state.last_action={'skills':skills,'tool':tool,'result':result,'session_id':st.session_state.session_id}
        with st.chat_message('assistant'):
            try:
                answer=ask_llm(prompt,result,context); st.markdown(answer); st.session_state.messages.append({'role':'assistant','content':answer}); honcho_save_turn(prompt,answer)
                try: asyncio.run(make_audio(answer,'/tmp/jarvis_v9.mp3')); st.audio('/tmp/jarvis_v9.mp3',format='audio/mp3',autoplay=True)
                except Exception as e: st.caption(f'Áudio indisponível: {e}')
            except Exception as e: st.error(f'Erro no Jarvis: {e}')
with tabs[1]:
    st.subheader('Tarefas')
    if not st.session_state.tasks: st.info('Nenhuma tarefa criada.')
    for t in st.session_state.tasks:
        c=st.checkbox(t['text'],value=t['done'],key=f"task_{t['id']}")
        if c!=t['done']: t['done']=c; save_json(TASKS_FILE,st.session_state.tasks)
with tabs[2]:
    st.subheader('Memória local de fallback'); st.json(st.session_state.memory) if st.session_state.memory else st.info('Nenhuma memória local salva.')
with tabs[3]:
    st.subheader('Memória Honcho'); st.write('Workspace:',HONCHO_WORKSPACE); st.write('Peer:',HONCHO_USER_ID); st.write('Sessão:',st.session_state.session_id); st.write('Status:',st.session_state.honcho_status)
    if st.button('Testar memória Honcho'):
        c=honcho_context('Quais informações importantes você tem sobre este usuário?'); st.session_state.honcho_context=c
        if c: st.success('Memória recuperada.'); st.code(c[:12000])
        else: st.warning('Não foi possível recuperar memória. Verifique HONCHO_API_KEY.')
with tabs[4]:
    for n,s in SKILLS.items():
        with st.expander(n): st.write(s['description']); st.write(', '.join(s['keywords']))
with tabs[5]:
    st.json(st.session_state.last_action or {'status':'Nenhuma ação executada'}); st.write('Voz:',VOICE); st.write('Modelo:',MODEL); st.write('Horário:',current_time())
