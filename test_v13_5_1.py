import sys
sys.path.insert(0,'.')
# Static source checks keep this test independent of Streamlit runtime.
from pathlib import Path
s=Path('app.py').read_text(encoding='utf-8')
assert 'def is_pc_intent' in s
assert 'def pc_clarification' in s
assert 'Local Agent está offline' in s
assert 'Qual página ou site você quer que eu abra?' in s
assert 'V14.0.0' in s
print('V14.0.0 OK')
