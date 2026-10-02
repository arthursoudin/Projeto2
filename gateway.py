import os, json, secrets, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse

import whatsapp, core, voice_io, store, security, orchestrator, devices, live_operations
import v19_command_os as v19

VERSION='19.0.0'
app=FastAPI(title='Jarvis Gateway',version=VERSION)
LOCAL_AGENT_TOKEN=os.getenv('LOCAL_AGENT_TOKEN','')
COMMANDS=[]
RESULTS=[]
AGENT={'last_seen':0.0,'info':{}}   # estado do agente local (para o dashboard)
HISTORY=[]                          # últimas medições de CPU/RAM
OVERNIGHT_DEFAULT={'enabled':False,'interval_minutes':30,'start_time':'22:00','end_time':'07:00','max_cycles':0}

def overnight_config():
    cfg=store.load('overnight_config',OVERNIGHT_DEFAULT.copy())
    if not isinstance(cfg,dict): cfg=OVERNIGHT_DEFAULT.copy()
    out=OVERNIGHT_DEFAULT.copy(); out.update(cfg); return out

INFO_KEYS={'version','computer','cpu_percent','ram_total_gb','ram_livre_gb','ram_em_uso_percent','disco_total_gb','disco_livre_gb','ligado_ha','rotinas_ativas','proxima_rotina','jarvis_folder','applications','application_count'}

def auth(token):
    return bool(LOCAL_AGENT_TOKEN) and secrets.compare_digest(token or '', LOCAL_AGENT_TOKEN)

def tasks():
    return core.load_tasks()

@app.get('/')
def root(): return {'service':'jarvis-gateway','version':VERSION}
@app.get('/health')
def health():
    return {
        'ok': True,
        'service': 'jarvis-gateway',
        'version': VERSION,
        'channels': ['whatsapp'],
        'whatsapp_configured': whatsapp.configured(),
        'honcho_configured': bool(os.getenv('HONCHO_API_KEY')),
        'local_agent_configured': bool(LOCAL_AGENT_TOKEN),
        'queued_commands': len(COMMANDS),
        'core_integrated': True,
        'build': '19.0.0-command-os-complete',
    }

@app.get('/system/status')
def system_status(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401, detail='Não autorizado')
    return orchestrator.status(
        agent_status=agent_status_dict(),
        whatsapp_status=whatsapp.status(),
    )

@app.get('/system/capabilities')
def system_capabilities(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401, detail='Não autorizado')
    return {'ok': True, 'capabilities': orchestrator.capabilities()}

@app.get('/system/events')
def system_events(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401, detail='Não autorizado')
    return {'ok': True, 'events': orchestrator.events()[-100:]}

@app.get('/system/live')
def system_live(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401, detail='Não autorizado')
    return live_operations.snapshot()

@app.get('/missions')
def get_missions(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401, detail='Não autorizado')
    return {'ok': True, 'missions': orchestrator.list_missions()}

@app.get('/devices')
def get_devices(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401, detail='Não autorizado')
    rows=devices.refresh_status()
    return {'ok': True, 'devices': rows, 'summary': devices.summary()}


@app.get('/devices/apps')
def devices_apps(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    rows=devices.list_devices()
    return {'ok':True,'devices':[{'id':d.get('id'),'name':d.get('name'),'status':d.get('status'),'applications':d.get('applications',[]),'application_count':d.get('application_count',0)} for d in rows]}

@app.get('/devices/{device_id}/apps')
def device_apps(device_id: str, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    d=devices.get_device(device_id)
    if not d: raise HTTPException(status_code=404,detail='Dispositivo não encontrado')
    return {'ok':True,'device_id':device_id,'name':d.get('name'),'status':d.get('status'),'applications':d.get('applications',[])}

@app.get('/os/status')
def v19_status(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'os':v19.status(),'gateway_version':VERSION}

@app.get('/os/diagnostics')
def v19_diagnostics(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    ag=agent_status_dict(); lv=(ag.get('info') or {}).get('version')
    vers={'gateway':VERSION}
    if lv: vers['local_agent']=str(lv)
    return {'ok':True,'version':v19.VERSION,'build':v19.BUILD,'agent':ag,'security':security.status(),'diagnostics':v19.diagnostics(vers)}

@app.get('/os/operations')
def v19_operations(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'operations':v19.list_operations(150),'stats':v19.operation_stats()}

@app.get('/os/agents')
def v19_agents(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'agents':v19.list_agents()}

@app.get('/os/missions')
def v19_missions(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'missions':v19.list_missions()}

@app.get('/os/workflows')
def v19_workflows(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'workflows':v19.list_workflows()}

@app.get('/os/snapshots')
def v19_snapshots(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'snapshots':v19.snapshots()}

@app.get('/os/resources')
def v19_resources(record: bool=False, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    if record: v19.record_resources()
    return {'ok':True,'resources':v19.resources(60),'current':v19.collect_resources()}

@app.get('/os/trace/{trace_id}')
def v19_trace(trace_id: str, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'trace_id':trace_id,'operations':v19.trace(trace_id)}

@app.get('/os/applications')
def v19_applications(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,**v19.application_center()}

@app.get('/os/device-groups')
def v19_device_groups(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'groups':v19.list_device_groups()}

@app.get('/uptime')
def uptime():
    # Endpoint público e leve para monitores externos, como UptimeRobot.
    return {'ok':True,'service':'jarvis-gateway','version':VERSION,'timestamp':datetime.now(timezone.utc).isoformat(),'monitor':'uptimerobot'}
@app.get('/overnight/config')
def get_overnight_config(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'config':overnight_config()}

@app.post('/overnight/config')
async def set_overnight_config(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    body=await request.json()
    if not isinstance(body,dict): raise HTTPException(status_code=400,detail='Configuração inválida')
    cfg=OVERNIGHT_DEFAULT.copy(); cfg.update(overnight_config())
    cfg['enabled']=bool(body.get('enabled',cfg['enabled']))
    cfg['interval_minutes']=max(1,min(1440,int(body.get('interval_minutes',cfg['interval_minutes']))))
    cfg['max_cycles']=max(0,min(10000,int(body.get('max_cycles',cfg['max_cycles']))))
    import re
    for key in ('start_time','end_time'):
        value=str(body.get(key,cfg[key])).strip()
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',value): raise HTTPException(status_code=400,detail=f'{key} inválido; use HH:MM')
        cfg[key]=value
    store.save('overnight_config',cfg)
    return {'ok':True,'config':cfg}

@app.get('/tasks')
def list_tasks(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    return {'ok':True,'tasks':tasks()}

# ------------------------------------------------------------------ fila de comandos do PC
ALLOWED_ACTIONS={'open_app','list_apps','open_folder','open_file','open_url','search_web','create_folder','create_file','append_file','read_file','list_files','move_path','copy_path','rename_path','delete_path','system_info','read_log','schedule_add','schedule_list','schedule_remove','schedule_toggle','upload_file','download_file','create_zip','document_info','search_files','create_workspace'}
CONFIRM_ACTIONS={'delete_path'}

def enqueue(action, params, agent='app', source='app', bypass_approval=False, target_device_id=None, trace_id=None):
    """V12.9: passa pela camada central de permissões antes de entrar na fila local."""
    params=params or {}
    if action not in ALLOWED_ACTIONS: raise HTTPException(status_code=400,detail='Ação não permitida')
    if not isinstance(params,dict): raise HTTPException(status_code=400,detail='params inválido')
    if action=='schedule_add':
        steps=params.get('steps')
        bad=not isinstance(steps,list) or any((not isinstance(x,dict)) or x.get('action') in CONFIRM_ACTIONS or str(x.get('action','')).startswith('schedule_') for x in steps)
        if bad: raise HTTPException(status_code=400,detail='Rotina com passo não permitido')
    p=security.policy()
    if p.get('kill_switch'):
        security.audit('action_blocked',action=action,agent=agent,reason='kill_switch',risk=security.risk_for(action),params=params)
        raise HTTPException(status_code=423,detail='Kill Switch ativo: novas ações estão bloqueadas.')
    if security.blocked(action):
        security.audit('action_blocked',action=action,agent=agent,reason='policy_block',risk=security.risk_for(action),params=params)
        raise HTTPException(status_code=403,detail='Ação bloqueada pela política de segurança.')
    cycle_id=params.get('_security_cycle_id','default')
    if security.needs_approval(action) and not bypass_approval and params.get('_security_approved') is not True:
        ap=security.create_approval(action,params,agent=agent,source=source)
        return {'pending_approval':True,'approval':ap}
    allowed, limit_error=security.check_limits(agent,cycle_id)
    if not allowed:
        security.audit('action_blocked',action=action,agent=agent,reason='limit',risk=security.risk_for(action),params=params)
        raise HTTPException(status_code=429,detail=limit_error)
    if len(COMMANDS)>=50: raise HTTPException(status_code=429,detail='Fila cheia')
    cid=secrets.token_urlsafe(12)
    clean=dict(params); clean.pop('_security_approved',None); clean.pop('_security_cycle_id',None)
    target = str(target_device_id or clean.pop('_target_device_id', '') or '').strip()
    if target and not devices.get_device(target):
        raise HTTPException(status_code=404, detail='Dispositivo alvo não encontrado.')
    COMMANDS.append({'id':cid,'action':action,'params':clean,'created_at':datetime.now(timezone.utc).isoformat(),'agent':agent,'target_device_id':target or None,'trace_id':str(trace_id)[:40] if trace_id else None})
    security.audit('action_queued',command_id=cid,action=action,agent=agent,risk=security.risk_for(action),params=clean)
    orchestrator.record_event('action_queued', source=agent, status='queued', command_id=cid, action=action)
    return cid

@app.post('/agent/commands')
async def add_command(request:Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    body=await request.json(); action=body.get('action'); params=body.get('params') or {}
    result=enqueue(action,params,agent=str(body.get('agent','app')),source=str(body.get('source','app')),target_device_id=body.get('target_device_id') or params.get('_target_device_id'),trace_id=body.get('trace_id'))
    if isinstance(result,dict): return {'ok':True,**result,'action':action}
    return {'ok':True,'command_id':result,'queued':True,'action':action}

@app.get('/agent/poll')
def poll_commands(x_agent_token: str|None = Header(default=None), x_device_id: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Agente não autorizado')
    AGENT['last_seen']=time.time()
    device_id=str(x_device_id or '').strip()
    if device_id:
        device=devices.get_device(device_id)
        if device: device['status']='online'; device['last_seen']=datetime.now(timezone.utc).isoformat(); store.save('devices',devices.list_devices())
    selected=[]; keep=[]
    for cmd in COMMANDS:
        target=cmd.get('target_device_id')
        if len(selected)<5 and (not target or target==device_id): selected.append(cmd)
        else: keep.append(cmd)
    COMMANDS[:] = keep
    return {'ok':True,'commands':selected,'device_id':device_id}

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
    if body.get('device_id'):
        try:
            devices.register(
                body.get('device_id'),
                name=body.get('computer'),
                capabilities=body.get('capabilities') if isinstance(body.get('capabilities'), list) else [],
                version=body.get('version'),
                telemetry=info,
            )
        except Exception:
            pass
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

def run_pc(action, params=None, target_device_id=None):
    """Mesmo formato do queue_pc_action do app: {'ok','result'|'error'}."""
    if not agent_online():
        return {'ok':False,'error':'O agente local está offline. Abra o start_agent.bat no PC.'}
    try:
        cid=enqueue(action,params or {},agent='whatsapp',source='whatsapp',target_device_id=target_device_id)
    except HTTPException as e:
        return {'ok':False,'error':str(e.detail)}
    if isinstance(cid,dict):  # aprovação de segurança pendente: não é timeout do agente
        return {'ok':False,'pending_approval':True,'approval':cid.get('approval'),'action':action,
                'error':'Ação aguardando aprovação de segurança no painel do Jarvis (aba Segurança).'}
    res=wait_result(cid)
    if res is None:
        return {'ok':False,'command_id':cid,'action':action,'error':'O agente local não respondeu a tempo. Verifique o start_agent.bat.'}
    return {'ok':bool(res.get('ok')),'command_id':cid,'action':action,'result':res}

# ------------------------------------------------------------------ V12.9 Security & Permissions
@app.get('/security/status')
def security_status(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,**security.status()}

@app.get('/security/approvals')
def security_approvals(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    return {'ok':True,'approvals':security.approvals()[-100:]}

@app.post('/security/approve/{approval_id}')
async def security_approve(approval_id: str, request: Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    item=security.decide_approval(approval_id,'approved')
    if not item: raise HTTPException(status_code=404,detail='Aprovação pendente não encontrada')
    try:
        result=enqueue(item['action'],dict(item.get('params') or {}),agent=item.get('agent','app'),source=item.get('source','app'),bypass_approval=True)
    except HTTPException as e:
        return {'ok':False,'approval':item,'error':str(e.detail)}
    cid=result if isinstance(result,str) else result.get('command_id')
    return {'ok':True,'approval':item,'command_id':cid,'queued':bool(cid)}

@app.post('/security/deny/{approval_id}')
def security_deny(approval_id: str, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    item=security.decide_approval(approval_id,'denied')
    if not item: raise HTTPException(status_code=404,detail='Aprovação pendente não encontrada')
    return {'ok':True,'approval':item}

@app.post('/security/kill-switch')
async def security_kill(request: Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    body=await request.json(); enabled=bool(body.get('enabled',True)) if isinstance(body,dict) else True
    p=security.policy(); p['kill_switch']=enabled; security.save_policy(p)
    if enabled: security.clear_pending()
    security.audit('kill_switch_changed',enabled=enabled)
    return {'ok':True,'kill_switch':enabled}

@app.post('/security/policy')
async def security_policy(request: Request, x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    body=await request.json(); return {'ok':True,'policy':security.save_policy(body if isinstance(body,dict) else {})}

@app.get('/security/audit')
def security_audit(x_agent_token: str|None = Header(default=None)):
    if not auth(x_agent_token): raise HTTPException(status_code=401,detail='Não autorizado')
    rows=store.load('security_audit',[]); return {'ok':True,'audit':rows[-100:] if isinstance(rows,list) else []}

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
