import os, json, secrets
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException

app=FastAPI(title='Jarvis Gateway',version='11.1')
LOCAL_AGENT_TOKEN=os.getenv('LOCAL_AGENT_TOKEN','')
COMMANDS=[]
RESULTS=[]

def auth(token):
    return bool(LOCAL_AGENT_TOKEN) and secrets.compare_digest(token or '', LOCAL_AGENT_TOKEN)

def tasks():
    from pathlib import Path
    p=Path('.jarvis_tasks.json')
    try: return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    except Exception: return []

@app.get('/')
def root(): return {'service':'jarvis-gateway','version':'11.1'}
@app.get('/health')
def health(): return {'ok':True,'service':'jarvis-gateway','version':'11.1','channels':['whatsapp'],'honcho_configured':bool(os.getenv('HONCHO_API_KEY')),'local_agent_configured':bool(LOCAL_AGENT_TOKEN),'queued_commands':len(COMMANDS)}
@app.get('/webhook')
def verify_webhook(): return {'ok':True,'message':'Webhook endpoint ativo','version':'11.1'}
@app.post('/webhook')
async def webhook(request:Request): return {'ok':True,'received':True,'memory_ready':bool(os.getenv('HONCHO_API_KEY')),'tasks':len(tasks())}
@app.get('/tasks')
def list_tasks(): return {'ok':True,'tasks':tasks()}

ALLOWED_ACTIONS={'open_app','open_folder','open_file','create_folder','create_file','system_info'}
@app.post('/agent/commands')
async def add_command(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json(); action=body.get('action'); params=body.get('params') or {}
    if action not in ALLOWED_ACTIONS: raise HTTPException(status_code=400,detail='Ação não permitida nesta V11.1')
    cid=secrets.token_urlsafe(12)
    COMMANDS.append({'id':cid,'action':action,'params':params,'created_at':datetime.now(timezone.utc).isoformat()})
    return {'ok':True,'command_id':cid,'queued':True,'action':action}

@app.get('/agent/poll')
def poll_commands(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    batch=COMMANDS[:5]; del COMMANDS[:len(batch)]
    return {'ok':True,'commands':batch}

@app.post('/agent/results')
async def agent_result(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json(); RESULTS.append(body); return {'ok':True}

@app.get('/agent/results')
def get_results(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    return {'ok':True,'results':RESULTS[-50:]}
