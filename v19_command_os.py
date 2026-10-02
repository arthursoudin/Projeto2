"""Jarvis V19 Command OS - unified control plane for V15-V19 capabilities.
Safe by design: orchestration/state only; dangerous actions still pass through
security.py and the existing Local Agent allowlist.
"""
from __future__ import annotations
import contextvars, hashlib, json, secrets, time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
import store

VERSION = "19.0.0"
BUILD = "command-os-complete"

AGENT_KEY="v19_agents"; WORKFLOW_KEY="v19_workflows"; MISSION_KEY="v19_missions"
OP_KEY="v19_operations"; RESOURCE_KEY="v19_resources"; SNAP_KEY="v19_snapshots"
LAB_KEY="v19_lab"; DEVICE_GROUP_KEY="v19_device_groups"
LIMIT=500
SNAP_LIMIT=20
WF_RUN_KEY="v19_workflow_runs"
_TRACE=contextvars.ContextVar('v19_trace',default=None)
_LAST_RES={'t':0.0}

# Ações que um workflow pode pedir. O Gateway/Permission Manager continua sendo a autoridade final.
SAFE_ACTIONS={'system_info','list_files','read_file','read_log','open_app','open_url','search_web','open_folder','open_file',
              'create_folder','create_file','append_file','copy_path','move_path','rename_path','delete_path',
              'list_apps','upload_file','download_file','create_zip','document_info','search_files','create_workspace'}
CONFIRM_ACTIONS={'delete_path'}
V19_SCOPE=[AGENT_KEY,WORKFLOW_KEY,MISSION_KEY,DEVICE_GROUP_KEY,LAB_KEY]
FULL_EXTRA=['tasks','memory','devices','missions','system_timeline']

def now(): return datetime.now(timezone.utc).isoformat()
def _rows(key):
    x=store.load(key,[]); return x if isinstance(x,list) else []
def _save(key, rows): store.save(key, rows[-LIMIT:]); return rows[-LIMIT:]
def _id(prefix): return f"{prefix}_{secrets.token_hex(7)}"
def _clean(v, depth=0):
    if isinstance(v,(str,int,float,bool)) or v is None: return v if not isinstance(v,str) else v[:1000]
    if depth>3: return str(v)[:500]
    if isinstance(v,dict): return {str(k)[:80]:_clean(x,depth+1) for k,x in list(v.items())[:40]}
    if isinstance(v,list): return [_clean(x,depth+1) for x in v[:40]]
    return str(v)[:500]

# ---- Agent Factory / temporary agents / agent network --------------------
def list_agents(): return _rows(AGENT_KEY)
def upsert_agent(name, role, description="", skills=None, temporary=False, enabled=True):
    name=str(name or '').strip()[:80]
    if not name: raise ValueError('Nome do agente é obrigatório.')
    rows=list_agents(); item=next((x for x in rows if x.get('name')==name),None)
    if item is None:
        item={'id':_id('agent'),'created_at':now()}; rows.append(item)
    item.update({'name':name,'role':str(role or 'general')[:60],'description':str(description or '')[:1000],
                 'skills':list(skills or [])[:30],'temporary':bool(temporary),'enabled':bool(enabled),'updated_at':now()})
    _save(AGENT_KEY,rows); return item

def remove_agent(agent_id):
    rows=[x for x in list_agents() if x.get('id')!=agent_id]
    _save(AGENT_KEY,rows); return len(rows)

def seed_agents():
    defaults=[
      ('planner','Planejador','Divide objetivos em etapas e escolhe especialistas',['planning','missions']),
      ('computer','Computer Agent','Planeja ações seguras no PC',['pc','verification']),
      ('pc','Agente do PC','Executa somente ações permitidas pelo Local Agent',['pc','filesystem']),
      ('tasks','Agente de Tarefas','Gerencia tarefas e prazos',['tasks']),
      ('memory','Agente de Memória','Gerencia memória explícita',['memory']),
      ('research','Agente de Pesquisa','Pesquisa e sintetiza informação',['web','research']),
      ('writer','Agente Redator','Produz documentos e respostas',['writing']),
      ('database','Agente de Banco','Trabalha com SQL/PostgreSQL de forma assistida',['sql','postgresql']),
      ('qa','Agente QA','Valida resultados e regressões',['qa','testing']),
      ('reviewer','Agente Revisor','Revisa missões, saídas e segurança',['review','security']),
    ]
    return [upsert_agent(*x) for x in defaults]

# ---- Missions / workflows -------------------------------------------------
def list_missions(): return _rows(MISSION_KEY)
def create_mission(goal, priority='normal', source='command_os'):
    goal=str(goal or '').strip()
    if not goal: raise ValueError('Objetivo vazio.')
    item={'id':_id('mission'),'goal':goal[:1500],'priority':priority,'source':source,'status':'queued',
          'created_at':now(),'updated_at':now(),'steps':[],'result':None,'review':None}
    rows=list_missions(); rows.append(item); _save(MISSION_KEY,rows); return item

def update_mission(mid, **changes):
    rows=list_missions(); found=None
    for x in rows:
        if x.get('id')==mid: found=x; break
    if not found:return None
    for k,v in changes.items(): found[k]=_clean(v)
    found['updated_at']=now(); _save(MISSION_KEY,rows); return found

def list_workflows(): return _rows(WORKFLOW_KEY)
def create_workflow(name, steps, description=''):
    if not isinstance(steps,list) or not steps: raise ValueError('Workflow precisa de etapas.')
    valid=[]
    for s in steps[:20]:
        if isinstance(s,dict) and s.get('action'):
            valid.append({'action':str(s['action'])[:80],'params':_clean(s.get('params') or {})})
    if not valid: raise ValueError('Nenhuma etapa válida.')
    item={'id':_id('wf'),'name':str(name or 'Workflow')[:100],'description':str(description or '')[:500],
          'steps':valid,'enabled':True,'created_at':now(),'updated_at':now()}
    rows=list_workflows(); rows.append(item); _save(WORKFLOW_KEY,rows); return item

def delete_workflow(wid):
    _save(WORKFLOW_KEY,[x for x in list_workflows() if x.get('id')!=wid]); return True

# ---- Operations / timeline -------------------------------------------------
@contextmanager
def trace_scope(trace_id=None):
    """Todas as operações iniciadas dentro do bloco compartilham o mesmo trace ID."""
    tid=trace_id or secrets.token_hex(12); tok=_TRACE.set(tid)
    try: yield tid
    finally: _TRACE.reset(tok)

def current_trace(): return _TRACE.get()

def start_operation(kind, source='command_os', target=None, payload=None, trace_id=None):
    op={'id':_id('op'),'trace_id':trace_id or _TRACE.get() or secrets.token_hex(12),'kind':str(kind)[:80],'source':str(source)[:80],
        'target':target,'status':'running','started_at':now(),'finished_at':None,'duration_ms':None,
        'payload':_clean(payload or {}),'result':None}
    rows=_rows(OP_KEY); rows.append(op); _save(OP_KEY,rows); return op

def finish_operation(op_id, ok, result=None, error=None):
    rows=_rows(OP_KEY); found=None
    for x in rows:
        if x.get('id')==op_id: found=x; break
    if not found:return None
    found['status']='success' if ok else 'error'; found['finished_at']=now()
    try:
        a=datetime.fromisoformat(found['started_at']); b=datetime.fromisoformat(found['finished_at']); found['duration_ms']=round((b-a).total_seconds()*1000,1)
    except Exception: pass
    found['result']=_clean(result); found['error']=str(error)[:1000] if error else None
    _save(OP_KEY,rows)
    try: _auto_resources()
    except Exception: pass
    return found

def trace(trace_id):
    """Todas as operações de um trace ID, em ordem cronológica."""
    return [x for x in _rows(OP_KEY) if x.get('trace_id')==str(trace_id)]

def list_operations(limit=100): return _rows(OP_KEY)[-max(1,min(300,int(limit))):]

def operation_stats():
    rows=list_operations(300); total=len(rows); ok=sum(x.get('status')=='success' for x in rows); err=sum(x.get('status')=='error' for x in rows)
    durations=[x.get('duration_ms') for x in rows if isinstance(x.get('duration_ms'),(int,float))]
    return {'total':total,'success':ok,'errors':err,'success_rate':round(ok/total*100,1) if total else 100.0,
            'avg_duration_ms':round(sum(durations)/len(durations),1) if durations else 0}

# ---- Resources -------------------------------------------------------------
def resource_snapshot(data):
    row={'id':_id('res'),'timestamp':now(),'data':_clean(data)}
    rows=_rows(RESOURCE_KEY); rows.append(row); _save(RESOURCE_KEY,rows); return row

def resources(limit=60): return _rows(RESOURCE_KEY)[-limit:]

# ---- Lab 2.0 ---------------------------------------------------------------
LAB_DEFAULT={'enabled':False,'interval_minutes':30,'max_cycles':0,'auto_apply':False,'last_cycle':None}
def lab_config():
    x=store.load(LAB_KEY,{}); out=dict(LAB_DEFAULT)
    if isinstance(x,dict): out.update(x)  # config parcial/vazia (ex.: snapshot antigo restaurado) não quebra o Lab
    return out

def set_lab(**changes):
    c=lab_config(); c.update({k:v for k,v in changes.items() if k in {'enabled','interval_minutes','max_cycles','auto_apply','last_cycle'}})
    c['interval_minutes']=max(1,min(1440,int(c['interval_minutes']))); c['max_cycles']=max(0,min(10000,int(c['max_cycles'])))
    # Production changes are never auto-applied by this layer.
    c['auto_apply']=False
    store.save(LAB_KEY,c); return c

# ---- Device network / resource groups -------------------------------------
def list_device_groups(): return _rows(DEVICE_GROUP_KEY)
def upsert_device_group(name, device_ids):
    name=str(name or '').strip()[:80]
    if not name: raise ValueError('Nome do grupo obrigatório.')
    rows=list_device_groups(); item=next((x for x in rows if x.get('name')==name),None)
    if item is None:item={'id':_id('dg'),'created_at':now()}; rows.append(item)
    item.update({'name':name,'device_ids':[str(x)[:120] for x in (device_ids or [])][:50],'updated_at':now()}); _save(DEVICE_GROUP_KEY,rows); return item

# ---- Snapshots -------------------------------------------------------------
def snapshot(label='manual'):
    keys=[AGENT_KEY,WORKFLOW_KEY,MISSION_KEY,OP_KEY,RESOURCE_KEY,LAB_KEY,DEVICE_GROUP_KEY,'tasks','memory','devices','missions','system_timeline']
    payload={k:store.load(k,[] if k not in {'memory',LAB_KEY} else {}) for k in keys}
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode(); digest=hashlib.sha256(raw).hexdigest()
    item={'id':_id('snap'),'label':str(label)[:100],'created_at':now(),'sha256':digest,'payload':payload}
    rows=_rows(SNAP_KEY); rows.append(item); store.save(SNAP_KEY,rows[-SNAP_LIMIT:]); return {'id':item['id'],'label':item['label'],'created_at':item['created_at'],'sha256':digest}

def snapshots(): return [{k:x.get(k) for k in ('id','label','created_at','sha256')} for x in _rows(SNAP_KEY)]

# ---- global status ---------------------------------------------------------
def status():
    return {'version':VERSION,'build':BUILD,'agents':len(list_agents()),'missions':len(list_missions()),
            'workflows':len(list_workflows()),'operations':operation_stats(),'resources':len(resources()),
            'lab':lab_config(),'device_groups':len(list_device_groups()),'snapshots':len(snapshots())}

seed_agents()

# ---- Auto planning / review / improvement (proposal-only) ------------------
def plan_mission(goal, available_agents=None, max_steps=8):
    """Create a deterministic starter plan. LLM planners may enrich it elsewhere."""
    g=str(goal or '').strip(); agents=available_agents or [x['name'] for x in list_agents() if x.get('enabled')]
    steps=[]
    low=g.lower()
    if any(k in low for k in ('pc','computador','chrome','excel','arquivo','pasta','abrir')): steps.append({'agent':'computer','action':'execute_safe_pc','status':'planned'})
    if any(k in low for k in ('pesquise','pesquisa','internet','web','compare')): steps.append({'agent':'research','action':'research','status':'planned'})
    if any(k in low for k in ('sql','postgres','banco de dados','database')): steps.append({'agent':'database','action':'database_assist','status':'planned'})
    if any(k in low for k in ('escreva','documento','relatorio','resumo','texto')): steps.append({'agent':'writer','action':'draft','status':'planned'})
    steps.append({'agent':'qa','action':'verify_result','status':'planned'})
    return {'goal':g,'steps':steps[:max_steps],'available_agents':agents[:50],'created_at':now()}

def review_result(result):
    ok=isinstance(result,dict) and bool(result.get('ok', result.get('status') in ('success','completed')))
    issues=[]
    if not isinstance(result,dict): issues.append('Resultado não estruturado.')
    elif not ok: issues.append('Operação reportou falha.')
    if isinstance(result,dict) and result.get('error'): issues.append(str(result['error'])[:300])
    return {'ok':not issues,'issues':issues,'checked_at':now(),'recommendation':'concluir' if not issues else 'revisar e repetir etapa'}

# ---- Resource Monitor --------------------------------------------------------
def collect_resources():
    """Coleta recursos do host do Gateway/Interface e a telemetria dos dispositivos registrados."""
    import os, shutil
    data={'operations':operation_stats(),'queued_missions':sum(x.get('status')=='queued' for x in list_missions())}
    try:
        du=shutil.disk_usage('.'); data['host_disk_total_gb']=round(du.total/1e9,1); data['host_disk_free_gb']=round(du.free/1e9,1)
    except Exception: pass
    try: data['host_load_1m']=round(os.getloadavg()[0],2)
    except Exception: pass
    try:
        mem={}
        for line in open('/proc/meminfo',encoding='utf-8'):
            k,_,v=line.partition(':'); mem[k]=int(v.split()[0])
        data['host_ram_used_pct']=round((1-mem['MemAvailable']/mem['MemTotal'])*100,1)
    except Exception: pass
    devs=[]
    try:
        import devices
        for d in devices.refresh_status():
            devs.append({'id':d.get('id'),'name':d.get('name'),'status':d.get('status'),'cpu_percent':d.get('cpu_percent'),
                         'ram_percent':d.get('ram_em_uso_percent'),'disk_free_gb':d.get('disco_livre_gb')})
    except Exception: pass
    data['devices']=devs; data['devices_online']=sum(d.get('status')=='online' for d in devs)
    return data

def record_resources(): return resource_snapshot(collect_resources())

def _auto_resources(min_interval=60):
    if time.time()-_LAST_RES['t']<min_interval: return None
    _LAST_RES['t']=time.time(); return record_resources()

# ---- Device Network ----------------------------------------------------------
def resolve_targets(device_ids=None, group_id=None):
    ids=[str(x) for x in (device_ids or [])]
    if group_id:
        g=next((x for x in list_device_groups() if x.get('id')==group_id or x.get('name')==group_id),None)
        if not g: raise ValueError('Grupo de dispositivos não encontrado.')
        ids+= [x for x in g.get('device_ids',[]) if x not in ids]
    return ids or [None]

# ---- Application Center ------------------------------------------------------
def application_center():
    try:
        import devices; rows=devices.refresh_status()
    except Exception: rows=[]
    apps={}; per=[]
    for d in rows:
        names=[]
        for a in (d.get('applications') or []):
            n=a.get('name') if isinstance(a,dict) else a
            if n: names.append(str(n)[:80])
        per.append({'device':d.get('name') or d.get('id'),'id':d.get('id'),'status':d.get('status'),'applications':len(names)})
        for n in names: apps.setdefault(n,[]).append(d.get('id'))
    return {'devices':per,'applications':[{'name':n,'devices':ids,'count':len(ids)} for n,ids in sorted(apps.items())]}

# ---- Workflow / Mission executors ---------------------------------------------
def _find(rows, rid): return next((x for x in rows if x.get('id')==rid),None)

def run_workflow(wid, runner, device_ids=None, group_id=None, confirmed=False):
    """Executa as etapas em ordem via `runner(action, params[, target_device_id])` (ex.: queue_pc_action).
    Para na primeira falha. Ações destrutivas exigem confirmed=True e ainda passam pelo Permission Manager."""
    wf=_find(list_workflows(),wid)
    if not wf: return {'ok':False,'status':'not_found','error':'Workflow não encontrado.'}
    if not wf.get('enabled',True): return {'ok':False,'status':'disabled','error':'Workflow desativado.'}
    try: targets=resolve_targets(device_ids,group_id)
    except ValueError as e: return {'ok':False,'status':'invalid_target','error':str(e)}
    out=[]; status='completed'; err=None
    with trace_scope() as tid:
        op=start_operation('workflow:'+wf['name'],payload={'workflow':wid,'targets':[t for t in targets if t]})
        for target in targets:
            for i,step in enumerate(wf['steps'],1):
                action=step['action']; params=dict(step.get('params') or {})
                rec={'n':i,'action':action,'target':target,'ok':None}
                out.append(rec)
                if action not in SAFE_ACTIONS:
                    rec['error']='Ação não permitida em workflows.'; status='failed'; err=rec['error']; break
                if action in CONFIRM_ACTIONS and not confirmed:
                    rec['error']='Confirmação necessária.'; status='awaiting_confirmation'; err=rec['error']; break
                if action in CONFIRM_ACTIONS: params['confirmed']=True
                try: r=runner(action,params,target_device_id=target) if target else runner(action,params)
                except Exception as e: r={'ok':False,'error':f'{type(e).__name__}: {e}'}
                r=r if isinstance(r,dict) else {'ok':False,'error':'Resposta inválida do executor.'}
                if r.get('pending_approval'):
                    rec['error']='Aguardando aprovação de segurança.'; status='awaiting_approval'; err=rec['error']; break
                rec['ok']=bool(r.get('ok'))
                if not rec['ok']:
                    rec['error']=str(r.get('error') or (r.get('result') or {}).get('error') or 'falhou')[:300]; status='failed'; err=rec['error']; break
            if status!='completed': break
        finish_operation(op['id'],status=='completed',result={'status':status,'steps':len(out)},error=err)
    rows=list_workflows(); w=_find(rows,wid)
    if w: w.update({'last_run_at':now(),'last_status':status,'last_trace_id':tid}); _save(WORKFLOW_KEY,rows)
    runs=_rows(WF_RUN_KEY); runs.append({'id':_id('run'),'workflow':wid,'status':status,'trace_id':tid,'at':now(),'steps':_clean(out)}); store.save(WF_RUN_KEY,runs[-100:])
    return {'ok':status=='completed','status':status,'trace_id':tid,'steps':out,'error':err}

def workflow_runs(wid=None, limit=20):
    rows=[x for x in _rows(WF_RUN_KEY) if wid is None or x.get('workflow')==wid]; return rows[-limit:]

_PRIO={'critical':0,'high':1,'normal':2,'low':3}

def run_mission(mid, team_runner=None):
    """Executa a missão com `team_runner(goal) -> {'ok','trace','reply'}` (ex.: app.run_team) e revisa o resultado."""
    m=_find(list_missions(),mid)
    if not m: return {'ok':False,'status':'not_found','error':'Missão não encontrada.'}
    if m.get('status')=='running': return {'ok':False,'status':'running','error':'Missão já em execução.'}
    with trace_scope() as tid:
        op=start_operation('mission',payload={'mission':mid,'goal':str(m.get('goal',''))[:200]})
        update_mission(mid,status='running',trace_id=tid,plan=plan_mission(m.get('goal','')))
        try:
            if team_runner is None: raise RuntimeError('Nenhum executor de equipe configurado.')
            res=team_runner(m['goal'])
        except Exception as e:
            res={'ok':False,'error':f'{type(e).__name__}: {e}','trace':[]}
        res=res if isinstance(res,dict) else {'ok':False,'error':'Resultado inválido do executor.','trace':[]}
        rev=review_result(res); status='completed' if rev['ok'] else 'failed'
        update_mission(mid,status=status,steps=res.get('trace') or [],result=str(res.get('reply') or res.get('error') or '')[:1500],review=rev)
        finish_operation(op['id'],rev['ok'],result={'status':status,'steps':len(res.get('trace') or [])},error=None if rev['ok'] else '; '.join(rev['issues']))
    return {'ok':rev['ok'],'status':status,'trace_id':tid,'review':rev,'reply':res.get('reply'),'error':res.get('error')}

def run_next_queued(team_runner=None):
    q=sorted([x for x in list_missions() if x.get('status')=='queued'],key=lambda x:(_PRIO.get(x.get('priority'),2),x.get('created_at','')))
    return run_mission(q[0]['id'],team_runner) if q else {'ok':False,'status':'empty','error':'Nenhuma missão na fila.'}

# ---- Snapshots: integridade + restore ------------------------------------------
def _digest(payload): return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()

def verify_snapshot(snapshot_id):
    item=_find(_rows(SNAP_KEY),snapshot_id)
    return bool(item) and _digest(item.get('payload'))==item.get('sha256')

def restore_snapshot(snapshot_id, scope='v19', confirm=False):
    """scope='v19' restaura só o estado do Command OS; 'full' inclui tarefas, memória, dispositivos e timeline.
    Sempre confere o SHA-256 e cria um snapshot 'pre-restore' antes de sobrescrever."""
    item=_find(_rows(SNAP_KEY),snapshot_id)
    if not item: return {'ok':False,'error':'Snapshot não encontrado.'}
    if _digest(item.get('payload'))!=item.get('sha256'): return {'ok':False,'error':'Integridade do snapshot falhou (SHA-256 diferente).'}
    keys=V19_SCOPE+(FULL_EXTRA if scope=='full' else [])
    keys=[k for k in keys if k in item['payload']]
    if not confirm: return {'ok':False,'needs_confirmation':True,'would_restore':keys,'error':'Confirmação necessária para restaurar.'}
    pre=snapshot('pre-restore-'+snapshot_id)
    for k in keys: store.save(k,item['payload'][k])
    return {'ok':True,'restored':keys,'pre_restore_snapshot':pre['id']}

# ---- Diagnóstico unificado ---------------------------------------------------------
def diagnostics(versions=None):
    """versions: {'gateway':'19.0.0','local_agent':'19.0.0'} informado por quem chama."""
    checks=[]
    def add(name,ok,detail=''): checks.append({'check':name,'ok':bool(ok),'detail':str(detail)[:300]})
    try: store.save('v19_diag_probe',{'t':now()}); add('store gravável',store.load('v19_diag_probe',None) is not None,store.backend())
    except Exception as e: add('store gravável',False,e)
    add('agentes padrão',len(list_agents())>=10,f'{len(list_agents())} agentes')
    vs={'command_os':VERSION}
    try:
        import orchestrator; vs['orchestrator']=orchestrator.VERSION
    except Exception: pass
    vs.update(versions or {})
    add('versões consistentes',len(set(vs.values()))==1,', '.join(f'{k}={v}' for k,v in vs.items()))
    st=operation_stats(); add('taxa de sucesso das operações',st['total']<5 or st['success_rate']>=80,f"{st['success_rate']}% em {st['total']} operações")
    try:
        import security; p=security.policy(); add('Permission Manager ativo',p.get('enabled',True),'kill switch ATIVO' if p.get('kill_switch') else 'kill switch desligado')
    except Exception as e: add('Permission Manager ativo',False,e)
    add('auto_apply do Lab bloqueado',lab_config().get('auto_apply') is False)
    snaps=snapshots(); add('snapshot existente',bool(snaps),f'{len(snaps)} snapshots')
    add('integridade do último snapshot',(not snaps) or verify_snapshot(snaps[-1]['id']),snaps[-1]['id'] if snaps else 'sem snapshots')
    return {'ok':all(c['ok'] for c in checks),'version':VERSION,'build':BUILD,'checked_at':now(),'checks':checks}

# ---- Lab 2.0 / Auto Improvement (apenas propostas) -------------------------------------
def auto_evaluations():
    st=operation_stats(); diag=diagnostics(); bad=[c['check'] for c in diag['checks'] if not c['ok']]
    return [
      {'evaluator':'quality','status':'pass' if st['total']<5 or st['success_rate']>=90 else 'attention','detail':f"{st['success_rate']}% de sucesso em {st['total']} operações"},
      {'evaluator':'security','status':'pass' if 'Permission Manager ativo' not in bad and 'auto_apply do Lab bloqueado' not in bad else 'attention','detail':'Permission Manager e auto_apply'},
      {'evaluator':'qa','status':'pass' if not bad else 'attention','detail':', '.join(bad) or 'todos os checks do diagnóstico passaram'},
    ]

def lab_cycle(evaluations=None):
    cycle={'id':_id('lab'),'timestamp':now(),'evaluations':_clean(evaluations if evaluations is not None else auto_evaluations()),'applied':False,
           'proposals':improvement_proposals(),'note':'V19 Lab só propõe mudanças; alterar produção exige ação humana explícita.'}
    store.save('v19_lab_last_cycle',cycle); set_lab(last_cycle=cycle['id']); return cycle

def improvement_proposals():
    s=status(); ops=list_operations(300); out=[]
    errs=[x for x in ops if x.get('status')=='error']
    if errs:
        by={}
        for x in errs: by[x.get('kind')]=by.get(x.get('kind'),0)+1
        k,n=max(by.items(),key=lambda kv:kv[1])
        out.append({'area':'reliability','priority':'high','proposal':f"'{k}' falhou {n}x nas últimas operações; revisar a causa e adicionar teste de regressão."})
    stale=[m for m in list_missions() if m.get('status')=='queued']
    if stale: out.append({'area':'missions','priority':'medium','proposal':f'{len(stale)} missão(ões) na fila sem execução; rode a fila ou cancele.'})
    if s['workflows'] and not any(w.get('last_run_at') for w in list_workflows()): out.append({'area':'workflows','priority':'low','proposal':'Há workflows salvos que nunca foram executados; teste-os em um dispositivo.'})
    if s['agents']<10: out.append({'area':'agents','priority':'medium','proposal':'Sincronizar agentes especialistas padrão.'})
    snaps=snapshots()
    if not snaps: out.append({'area':'recovery','priority':'medium','proposal':'Nenhum snapshot criado; registre um antes de mudanças grandes.'})
    if not s['lab'].get('enabled'): out.append({'area':'lab','priority':'low','proposal':'Ativar o Laboratório para gerar relatórios de melhoria sem auto-aplicar código.'})
    return out
