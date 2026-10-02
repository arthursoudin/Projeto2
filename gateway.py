import os, json, secrets
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException

VERSION='12.4'
app=FastAPI(title='Jarvis Gateway', version=VERSION)
LOCAL_AGENT_TOKEN=os.getenv('LOCAL_AGENT_TOKEN','')
COMMANDS=[]
RESULTS=[]
AGENT_STATUS={'online':False,'last_heartbeat':None,'version':None,'hostname':None,'platform':None}

ALLOWED_ACTIONS={'open_app','open_folder','open_file','open_url','search_web','create_folder','create_file','append_file','read_file','list_files','move_path','copy_path','rename_path','delete_path','system_info','read_log'}
CONFIRM_ACTIONS={'delete_path','create_file','append_file'}

def auth(token): return bool(LOCAL_AGENT_TOKEN) and secrets.compare_digest(token or '', LOCAL_AGENT_TOKEN)
def tasks():
    from pathlib import Path
    p=Path('.jarvis_tasks.json')
    try: return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    except Exception: return []

def heartbeat_fresh(seconds=30):
    if not AGENT_STATUS.get('last_heartbeat'): return False
    try: return (datetime.now(timezone.utc)-datetime.fromisoformat(AGENT_STATUS['last_heartbeat'])).total_seconds() <= seconds
    except Exception: return False

@app.get('/')
def root(): return {'service':'jarvis-gateway','version':VERSION}
@app.get('/health')
def health(): return {'ok':True,'service':'jarvis-gateway','version':VERSION,'channels':['whatsapp'],'honcho_configured':bool(os.getenv('HONCHO_API_KEY')),'local_agent_configured':bool(LOCAL_AGENT_TOKEN),'local_agent_online':heartbeat_fresh(),'queued_commands':len(COMMANDS)}
@app.get('/webhook')
def verify_webhook(): return {'ok':True,'message':'Webhook endpoint ativo','version':VERSION}
@app.post('/webhook')
async def webhook(request:Request): return {'ok':True,'received':True,'memory_ready':bool(os.getenv('HONCHO_API_KEY')),'tasks':len(tasks())}
@app.get('/tasks')
def list_tasks(): return {'ok':True,'tasks':tasks()}

@app.get('/agent/status')
def agent_status(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    return {'ok':True, **AGENT_STATUS, 'online':heartbeat_fresh(), 'queued_commands':len(COMMANDS)}

@app.post('/agent/heartbeat')
async def heartbeat(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json()
    AGENT_STATUS.update({'online':True,'last_heartbeat':datetime.now(timezone.utc).isoformat(timespec='seconds'),'version':body.get('version'),'hostname':body.get('hostname'),'platform':body.get('platform')})
    return {'ok':True,'online':True,'server_time':datetime.now(timezone.utc).isoformat(timespec='seconds')}

@app.post('/agent/commands')
async def add_command(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json(); action=body.get('action'); params=body.get('params') or {}
    if action not in ALLOWED_ACTIONS: raise HTTPException(status_code=400,detail='Ação não permitida')
    if not isinstance(params,dict): raise HTTPException(status_code=400,detail='params inválido')
    if action in CONFIRM_ACTIONS and params.get('confirmed') is not True: raise HTTPException(status_code=400,detail='Ação exige confirmação')
    if len(COMMANDS)>=50: raise HTTPException(status_code=429,detail='Fila cheia')
    cid=secrets.token_urlsafe(12)
    COMMANDS.append({'id':cid,'command_id':cid,'action':action,'params':params,'created_at':datetime.now(timezone.utc).isoformat()})
    return {'ok':True,'command_id':cid,'queued':True,'action':action}

@app.get('/agent/poll')
def poll_commands(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
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
