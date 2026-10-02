from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import orchestrator
import live_operations

def test_live_snapshot_empty(monkeypatch):
    monkeypatch.setattr(orchestrator, 'events', lambda: [])
    out=live_operations.snapshot()
    assert out['ok'] is True
    assert out['current'] is None
    assert out['running'] == []

def test_live_snapshot_completed(monkeypatch):
    events=[
        {'timestamp':'2026-10-02T18:00:00+00:00','event':'agent_started','status':'running','data':{'operation_id':'op1','agent':'pc','instruction':'Abrir VS Code'}},
        {'timestamp':'2026-10-02T18:00:02+00:00','event':'agent_completed','status':'success','data':{'operation_id':'op1','agent':'pc','duration_ms':2000,'result':'VS Code aberto','ok':True}},
    ]
    monkeypatch.setattr(orchestrator, 'events', lambda: events)
    out=live_operations.snapshot()
    assert out['current']['operation_id']=='op1'
    assert out['current']['status']=='success'
    assert out['current']['duration_ms']==2000

def test_live_snapshot_running(monkeypatch):
    events=[{'timestamp':'2026-10-02T18:00:00+00:00','event':'agent_started','status':'running','data':{'operation_id':'op2','agent':'computer','instruction':'Executando tarefa'}}]
    monkeypatch.setattr(orchestrator, 'events', lambda: events)
    out=live_operations.snapshot()
    assert out['current']['operation_id']=='op2'
    assert out['current']['status']=='running'
    assert out['running'][0]['agent']=='computer'
