import notifications

notes = notifications.build_notifications(
    agent={'ok': True, 'online': False},
    security={'kill_switch': False, 'pending': 2},
    missions=[{'id':'m1','status':'failed','goal':'Teste'}],
    tasks=[{'id':1,'status':'pending','due_at':'2000-01-01T00:00:00','text':'Teste'}],
    events=[],
    live={'current': None},
)
assert notes
ids={n['id'] for n in notes}
assert 'agent-offline' in ids
assert 'security-approvals' in ids
assert 'mission-failed' in ids
assert 'tasks-overdue' in ids
print('V13.4 notification tests: OK')
