"""Jarvis V12.9 — Security & Permissions.
Centraliza risco, aprovações, auditoria, kill switch e limites de ação.
"""
from __future__ import annotations
import secrets
from datetime import datetime, timezone
import store

DEFAULT_POLICY = {
    'enabled': True,
    'kill_switch': False,
    'max_actions_per_cycle': 20,
    'max_actions_per_agent': 10,
    'approval_required_for': ['medium', 'high'],
    'blocked_actions': ['delete_path'],
}

RISK = {
    'open_app':'low','open_folder':'low','open_file':'low','open_url':'low','search_web':'low',
    'system_info':'low','read_log':'low','list_files':'low','read_file':'low','schedule_list':'low',
    'create_folder':'medium','create_file':'medium','append_file':'medium','move_path':'medium',
    'copy_path':'medium','rename_path':'medium','schedule_add':'medium','schedule_toggle':'medium',
    'schedule_remove':'medium','upload_file':'medium','download_file':'low','create_zip':'medium','document_info':'low','search_files':'low','create_workspace':'medium','delete_path':'high',
}

def policy():
    p=store.load('security_policy', DEFAULT_POLICY.copy())
    if not isinstance(p,dict): p=DEFAULT_POLICY.copy()
    out=DEFAULT_POLICY.copy(); out.update(p); return out

def save_policy(p):
    base=DEFAULT_POLICY.copy(); base.update(p or {})
    base['max_actions_per_cycle']=max(1,min(100, int(base.get('max_actions_per_cycle',20))))
    base['max_actions_per_agent']=max(1,min(50, int(base.get('max_actions_per_agent',10))))
    store.save('security_policy',base); return base

def risk_for(action): return RISK.get(str(action), 'high')

def blocked(action): return str(action) in set(policy().get('blocked_actions',[]))

def needs_approval(action):
    return risk_for(action) in set(policy().get('approval_required_for',[]))

def _list(key, limit=300):
    x=store.load(key,[])
    return x[-limit:] if isinstance(x,list) else []

def audit(event, **fields):
    row={'id':secrets.token_urlsafe(10),'timestamp':datetime.now(timezone.utc).isoformat(),'event':event}
    for k,v in fields.items():
        if isinstance(v,str): row[k]=v[:500]
        elif isinstance(v,(int,float,bool)) or v is None: row[k]=v
        elif isinstance(v,dict): row[k]={str(a)[:50]:str(b)[:300] for a,b in list(v.items())[:12]}
        else: row[k]=str(v)[:500]
    rows=_list('security_audit',300); rows.append(row); store.save('security_audit',rows)
    return row

def approvals(): return _list('security_approvals',100)

def create_approval(action, params, agent='unknown', source='app'):
    item={'id':secrets.token_urlsafe(12),'created_at':datetime.now(timezone.utc).isoformat(),
          'action':action,'params':params or {},'agent':agent,'source':source,'risk':risk_for(action),'status':'pending'}
    rows=approvals(); rows.append(item); store.save('security_approvals',rows)
    audit('approval_requested',approval_id=item['id'],action=action,agent=agent,risk=item['risk'],params=item['params'])
    return item

def decide_approval(approval_id, decision):
    rows=approvals(); found=None
    for x in rows:
        if x.get('id')==approval_id and x.get('status')=='pending':
            x['status']=decision; x['decided_at']=datetime.now(timezone.utc).isoformat(); found=x; break
    store.save('security_approvals',rows)
    if found: audit('approval_decision',approval_id=approval_id,decision=decision,action=found.get('action'),risk=found.get('risk'))
    return found

def clear_pending():
    rows=approvals()
    changed=0
    for x in rows:
        if x.get('status')=='pending': x['status']='cancelled'; changed+=1
    store.save('security_approvals',rows)
    if changed: audit('kill_switch_cancelled_pending',count=changed)
    return changed


def check_limits(agent, cycle_id):
    key=str(cycle_id or 'default')
    counts=store.load('security_counters',{})
    if not isinstance(counts,dict): counts={}
    item=counts.get(key,{}) if isinstance(counts.get(key),dict) else {}
    total=int(item.get('total',0)); by_agent=item.get('agents',{}) if isinstance(item.get('agents',{}),dict) else {}
    p=policy(); limit=int(p.get('max_actions_per_cycle',20)); alimit=int(p.get('max_actions_per_agent',10))
    if total >= limit: return False, f'Limite do ciclo atingido ({limit} ações).'
    if int(by_agent.get(agent,0)) >= alimit: return False, f'Limite do agente atingido ({alimit} ações).'
    item['total']=total+1; by_agent[agent]=int(by_agent.get(agent,0))+1; item['agents']=by_agent
    counts[key]=item
    # Mantém poucos ciclos recentes.
    if len(counts)>100: counts=dict(list(counts.items())[-100:])
    store.save('security_counters',counts)
    return True,''

def status():
    p=policy(); a=approvals();
    return {'policy':p,'kill_switch':bool(p.get('kill_switch')),
            'pending':sum(1 for x in a if x.get('status')=='pending'),
            'approved':sum(1 for x in a if x.get('status')=='approved'),
            'denied':sum(1 for x in a if x.get('status')=='denied'),
            'audit_entries':len(_list('security_audit',300))}
