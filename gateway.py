import os, json, secrets, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse

import whatsapp, core, voice_io

VERSION='12.5.0'
app=FastAPI(title='Jarvis Gateway',version=VERSION)
LOCAL_AGENT_TOKEN=os.getenv('LOCAL_AGENT_TOKEN','')
COMMANDS=[]
RESULTS=[]
AGENT={'last_seen':0.0,'info':{}}   # estado do agente local (para o dashboard)
HISTORY=[]                          # últimas medições de CPU/RAM
INFO_KEYS={'version','computer','cpu_percent','ram_total_gb','ram_livre_gb','ram_em_uso_percent','disco_total_gb','disco_livre_gb','ligado_ha','rotinas_ativas','proxima_rotina','jarvis_folder'}

def auth(token):
    return bool(LOCAL_AGENT_TOKEN) and secrets.compare_digest(token or '', LOCAL_AGENT_TOKEN)

def tasks():
    return core.load_tasks()

@app.get('/')
def root(): return {'service':'jarvis-gateway','version':VERSION}
@app.get('/health')
def health(): return {'ok':True,'service':'jarvis-gateway','version':VERSION,'channels':['whatsapp'],'whatsapp_configured':whatsapp.configured(),'honcho_configured':bool(os.getenv('HONCHO_API_KEY')),'local_agent_configured':bool(LOCAL_AGENT_TOKEN),'queued_commands':len(COMMANDS)}
@app.get('/tasks')
def list_tasks(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    return {'ok':True,'tasks':tasks()}

# ------------------------------------------------------------------ fila de comandos do PC
ALLOWED_ACTIONS={'open_app','open_folder','open_file','open_url','search_web','create_folder','create_file','append_file','read_file','list_files','move_path','copy_path','rename_path','delete_path','system_info','read_log','schedule_add','schedule_list','schedule_remove','schedule_toggle'}
CONFIRM_ACTIONS={'delete_path'}

def enqueue(action, params):
    """Valida e coloca um comando na fila do agente. Levanta HTTPException se for recusado."""
    params=params or {}
    if action not in ALLOWED_ACTIONS: raise HTTPException(status_code=400,detail='Ação não permitida')
    if not isinstance(params,dict): raise HTTPException(status_code=400,detail='params inválido')
    if action in CONFIRM_ACTIONS and params.get('confirmed') is not True: raise HTTPException(status_code=400,detail='Ação exige confirmação')
    if action=='schedule_add':
        steps=params.get('steps')
        bad=not isinstance(steps,list) or any((not isinstance(x,dict)) or x.get('action') in CONFIRM_ACTIONS or str(x.get('action','')).startswith('schedule_') for x in steps)
        if bad: raise HTTPException(status_code=400,detail='Rotina com passo não permitido')
    if len(COMMANDS)>=50: raise HTTPException(status_code=429,detail='Fila cheia')
    cid=secrets.token_urlsafe(12)
    COMMANDS.append({'id':cid,'action':action,'params':params,'created_at':datetime.now(timezone.utc).isoformat()})
    return cid

@app.post('/agent/commands')
async def add_command(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json(); action=body.get('action'); params=body.get('params') or {}
    cid=enqueue(action,params)
    return {'ok':True,'command_id':cid,'queued':True,'action':action}

@app.get('/agent/poll')
def poll_commands(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    AGENT['last_seen']=time.time()
    batch=COMMANDS[:5]; del COMMANDS[:len(batch)]
    return {'ok':True,'commands':batch}

@app.post('/agent/results')
async def agent_result(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json(); RESULTS.append(body); del RESULTS[:-200]; return {'ok':True}

@app.get('/agent/results')
def get_results(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    return {'ok':True,'results':RESULTS[-50:]}

def _clean(v):
    if isinstance(v,(int,float,bool)) or v is None: return v
    if isinstance(v,str): return v[:200]
    if isinstance(v,dict): return {str(k)[:40]:_clean(x) for k,x in list(v.items())[:6]}
    return None

@app.post('/agent/heartbeat')
async def heartbeat(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json()
    if not isinstance(body,dict): raise HTTPException(status_code=400,detail='corpo inválido')
    info={k:_clean(v) for k,v in body.items() if k in INFO_KEYS}
    AGENT['info']=info; AGENT['last_seen']=time.time()
    HISTORY.append({'t':AGENT['last_seen'],'cpu':info.get('cpu_percent'),'ram':info.get('ram_em_uso_percent')}); del HISTORY[:-120]
    return {'ok':True}

def agent_online():
    return bool(AGENT['last_seen']) and (time.time()-AGENT['last_seen'])<30

def agent_status_dict():
    age=(time.time()-AGENT['last_seen']) if AGENT['last_seen'] else None
    return {'ok':True,'online':age is not None and age<30,'age_seconds':round(age,1) if age is not None else None,
            'info':AGENT['info'],'history':HISTORY[-60:],'queued_commands':len(COMMANDS),'whatsapp':whatsapp.status()}

@app.get('/agent/status')
def agent_status(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    return agent_status_dict()

# ------------------------------------------------------------------ ponte interna (WhatsApp -> PC)
def wait_result(cid, timeout=15):
    deadline=time.time()+timeout
    while time.time()<deadline:
        for item in list(RESULTS):
            if item.get('command_id')==cid:
                res=item.get('result') or {}
                return res
        time.sleep(0.5)
    return None

def run_pc(action, params=None):
    """Mesmo formato do queue_pc_action do app: {'ok','result'|'error'}."""
    if not agent_online():
        return {'ok':False,'error':'O agente local está offline. Abra o start_agent.bat no PC.'}
    try:
        cid=enqueue(action,params or {})
    except HTTPException as e:
        return {'ok':False,'error':str(e.detail)}
    res=wait_result(cid)
    if res is None:
        return {'ok':False,'command_id':cid,'action':action,'error':'O agente local não respondeu a tempo. Verifique o start_agent.bat.'}
    return {'ok':bool(res.get('ok')),'command_id':cid,'action':action,'result':res}

_BRAIN={'obj':None}
def get_brain():
    if _BRAIN['obj'] is None:
        _BRAIN['obj']=core.Brain(run_pc=run_pc,llm=core.make_llm(),agent_status=agent_status_dict,channel='whatsapp')
    return _BRAIN['obj']

# ------------------------------------------------------------------ WhatsApp (V12.1)
def process_whatsapp(msg):
    """Roda em segundo plano: entende a mensagem (texto ou áudio), executa e responde."""
    num=msg['from']; prefix=''
    try:
        whatsapp.mark_read(msg['id'])
        kind=msg['type']; text=msg['text']
        if kind=='audio':
            data,mime=whatsapp.download_media(msg['media_id'])
            text=voice_io.transcribe(data,filename=whatsapp.audio_filename(mime))
            prefix=f'🎤 Entendi: "{text}"\n\n'
        elif kind!='text':
            whatsapp.send_text(num,'Por enquanto eu entendo texto e áudio. 🙂'); return
        out=get_brain().handle(core_user(num),text)
        whatsapp.send_text(num,prefix+out['reply'])
    except voice_io.VoiceError as e:
        whatsapp.send_text(num,f'🎤 {e}')
    except RuntimeError as e:
        whatsapp.send_text(num,f'⚠️ {e}')
    except Exception as e:
        whatsapp.log_event('out',num,'erro',False,type(e).__name__)
        whatsapp.send_text(num,'Tive um erro ao processar sua mensagem. Tente de novo.')

def core_user(number):
    d=''.join(c for c in str(number) if c.isdigit())
    return 'wa_'+d

@app.get('/webhook')
def verify_webhook(request:Request):
    q=request.query_params
    if q.get('hub.mode'):
        ch=whatsapp.verify_challenge(q.get('hub.mode'),q.get('hub.verify_token'),q.get('hub.challenge'))
        if ch is None: raise HTTPException(status_code=403,detail='Token de verificação inválido')
        return PlainTextResponse(ch)
    return {'ok':True,'message':'Webhook endpoint ativo','version':VERSION,'whatsapp_configured':whatsapp.configured()}

@app.post('/webhook')
async def webhook(request:Request, background:BackgroundTasks):
    raw=await request.body()
    if not whatsapp.valid_signature(raw,request.headers.get('x-hub-signature-256')):
        raise HTTPException(status_code=403,detail='Assinatura inválida (confira WHATSAPP_APP_SECRET)')
    try: payload=json.loads(raw or b'{}')
    except Exception: raise HTTPException(status_code=400,detail='JSON inválido')
    queued=0
    for m in whatsapp.extract_messages(payload):
        if whatsapp.already_seen(m['id']): continue
        if not whatsapp.is_allowed(m['from']):
            whatsapp.log_event('in',m['from'],'bloqueado',False,'número não autorizado'); continue
        if not whatsapp.rate_ok(m['from']):
            whatsapp.log_event('in',m['from'],m['type'],False,'limite de ritmo'); continue
        whatsapp.log_event('in',m['from'],'áudio' if m['type']=='audio' else m['type'])
        background.add_task(process_whatsapp,m); queued+=1
    return {'ok':True,'received':True,'queued':queued}
