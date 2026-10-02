import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ['JARVIS_STORE_DIR']=tempfile.mkdtemp(prefix='jarvis_v19_test_')
import v19_command_os as v
def test_seed(): assert len(v.list_agents()) >= 10

def test_agent_factory():
    a=v.upsert_agent('test-temp','qa','x',['qa'],True); assert a['temporary'] is True

def test_mission_workflow():
    m=v.create_mission('test mission'); assert m['status']=='queued'
    w=v.create_workflow('test wf',[{'action':'noop','params':{}}]); assert w['steps']

def test_operation():
    o=v.start_operation('test'); r=v.finish_operation(o['id'],True,{'ok':True}); assert r['status']=='success'

def test_lab_snapshot():
    assert v.set_lab(enabled=True)['enabled'] is True
    s=v.snapshot('test'); assert len(s['sha256'])==64


# ---------------- V19 completo: executores, trace, recursos, restore ----------------
def _ok_runner(calls):
    def r(action, params=None, target_device_id=None):
        calls.append((action, dict(params or {}), target_device_id)); return {'ok': True, 'result': {'ok': True}}
    return r

def test_workflow_runs_steps_in_order_with_one_trace():
    calls = []
    wf = v.create_workflow('wf-ok', [{'action': 'system_info', 'params': {}}, {'action': 'create_folder', 'params': {'name': 'x'}}])
    res = v.run_workflow(wf['id'], _ok_runner(calls))
    assert res['ok'] and res['status'] == 'completed'
    assert [c[0] for c in calls] == ['system_info', 'create_folder']
    ops = v.trace(res['trace_id'])
    assert ops and all(o['trace_id'] == res['trace_id'] for o in ops)
    assert v.workflow_runs(wf['id'])[-1]['trace_id'] == res['trace_id']

def test_workflow_stops_on_first_failure():
    calls = []
    def r(action, params=None, target_device_id=None):
        calls.append(action); return {'ok': action != 'create_folder', 'error': 'boom'}
    wf = v.create_workflow('wf-fail', [{'action': 'create_folder'}, {'action': 'system_info'}])
    res = v.run_workflow(wf['id'], r)
    assert res['status'] == 'failed' and calls == ['create_folder']

def test_workflow_rejects_unknown_action_and_never_calls_runner():
    calls = []
    wf = v.create_workflow('wf-bad', [{'action': 'format_disk'}])
    res = v.run_workflow(wf['id'], _ok_runner(calls))
    assert res['status'] == 'failed' and calls == []

def test_workflow_destructive_needs_confirmation():
    calls = []
    wf = v.create_workflow('wf-del', [{'action': 'delete_path', 'params': {'name': 'x'}}])
    res = v.run_workflow(wf['id'], _ok_runner(calls))
    assert res['status'] == 'awaiting_confirmation' and calls == []
    res = v.run_workflow(wf['id'], _ok_runner(calls), confirmed=True)
    assert calls and calls[0][1]['confirmed'] is True

def test_workflow_reports_pending_approval():
    wf = v.create_workflow('wf-appr', [{'action': 'create_file', 'params': {}}])
    res = v.run_workflow(wf['id'], lambda a, p=None, target_device_id=None: {'ok': False, 'pending_approval': True})
    assert res['status'] == 'awaiting_approval'

def test_workflow_on_device_group():
    calls = []
    g = v.upsert_device_group('grp-test', ['pc-a', 'pc-b'])
    wf = v.create_workflow('wf-grp', [{'action': 'system_info'}])
    res = v.run_workflow(wf['id'], _ok_runner(calls), group_id=g['id'])
    assert res['ok'] and [c[2] for c in calls] == ['pc-a', 'pc-b']

def test_mission_executes_and_is_reviewed():
    m = v.create_mission('missão ok')
    res = v.run_mission(m['id'], lambda goal: {'ok': True, 'trace': [{'n': 1, 'ok': True}], 'reply': 'feito'})
    assert res['ok'] and v._find(v.list_missions(), m['id'])['status'] == 'completed'
    assert v._find(v.list_missions(), m['id'])['review']['ok'] is True

def test_mission_failure_and_missing_executor_are_honest():
    m = v.create_mission('missão sem executor')
    res = v.run_mission(m['id'], None)
    assert not res['ok'] and v._find(v.list_missions(), m['id'])['status'] == 'failed'
    m2 = v.create_mission('missão falha')
    assert not v.run_mission(m2['id'], lambda g: {'ok': False, 'reply': 'x', 'trace': []})['ok']

def test_run_next_queued_respects_priority():
    seen = []
    a = v.create_mission('baixa prioridade', 'low'); b = v.create_mission('crítica', 'critical')
    for mm in v.list_missions():
        if mm['id'] not in (a['id'], b['id']) and mm['status'] == 'queued': v.update_mission(mm['id'], status='cancelled')
    v.run_next_queued(lambda g: seen.append(g) or {'ok': True, 'trace': []})
    assert seen == ['crítica']

def test_trace_scope_shared_by_nested_operations():
    with v.trace_scope() as tid:
        a = v.start_operation('a'); b = v.start_operation('b')
    assert a['trace_id'] == b['trace_id'] == tid
    assert v.start_operation('c')['trace_id'] != tid

def test_resources_collected_with_numeric_values():
    row = v.record_resources()
    assert isinstance(row['data']['operations']['total'], int) and 'queued_missions' in row['data']
    assert v.resources(1)

def test_snapshot_restore_roundtrip_and_tamper_detection():
    v.upsert_agent('snap-agent', 'qa'); snap = v.snapshot('antes')
    v.remove_agent(v._find(v.list_agents(), v.list_agents()[-1]['id'])['id'])
    assert v.verify_snapshot(snap['id'])
    r = v.restore_snapshot(snap['id'])
    assert r['needs_confirmation'] and not r['ok']
    r = v.restore_snapshot(snap['id'], confirm=True)
    assert r['ok'] and any(x['name'] == 'snap-agent' for x in v.list_agents()) and r['pre_restore_snapshot']
    rows = v._rows(v.SNAP_KEY); rows[-1]['payload'][v.AGENT_KEY] = []; v._save(v.SNAP_KEY, rows)
    assert not v.restore_snapshot(rows[-1]['id'], confirm=True)['ok']

def test_application_center_and_diagnostics():
    assert 'applications' in v.application_center()
    d = v.diagnostics({'gateway': v.VERSION})
    assert d['checks'] and any(c['check'] == 'versões consistentes' and c['ok'] for c in d['checks'])
    assert not v.diagnostics({'gateway': '0.0.1'})['ok']

def test_lab_cycle_is_proposal_only_and_auto_evaluated():
    c = v.lab_cycle()
    assert c['applied'] is False and {e['evaluator'] for e in c['evaluations']} == {'quality', 'security', 'qa'}
    assert v.set_lab(auto_apply=True)['auto_apply'] is False

def test_lab_survives_restore_of_snapshot_taken_before_lab_was_configured():
    v.store.save(v.LAB_KEY, {})  # estado "nunca configurado" dentro do snapshot
    sn = v.snapshot('lab-vazio'); assert v.restore_snapshot(sn['id'], confirm=True)['ok']
    assert v.set_lab(enabled=True)['interval_minutes'] == 30
