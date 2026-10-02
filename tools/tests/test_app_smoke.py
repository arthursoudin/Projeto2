"""Executa o app.py de verdade contra um Streamlit/OpenAI/edge_tts simulados (sem rede)."""
import json, os, runpy, sys, tempfile, types, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class SState(dict):
    __getattr__ = lambda s, k: s[k] if k in s else (_ for _ in ()).throw(AttributeError(k))
    def __setattr__(s, k, v): s[k] = v


def build_streamlit(state, prompt):
    st = mock.MagicMock(name='streamlit')
    st.session_state = state
    st.cache_resource = lambda *a, **k: (lambda f: f)
    st.fragment = lambda *a, **k: (lambda f: f)
    st.tabs = lambda names: [mock.MagicMock() for _ in names]
    st.columns = lambda n: [mock.MagicMock(**{'button.return_value': False}) for _ in range(n if isinstance(n, int) else len(n))]
    st.chat_input.return_value = prompt
    st.audio_input.return_value = None
    st.button.return_value = False
    st.toggle.return_value = True
    st.selectbox.side_effect = lambda label, opts, **k: opts[k.get('index', 0)]
    st.number_input.return_value = 1
    return st


def install_fakes(st):
    sys.modules['streamlit'] = st
    openai = types.ModuleType('openai')

    class Msg:  # resposta do LLM falso
        def __init__(s, c): s.content = c
    class Client:
        def __init__(s, **k):
            s.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=s.create))
        def create(s, model, messages, temperature=0.4):
            sysmsg = messages[0]['content']
            if sysmsg.startswith('Você é o Planejador'):
                out = json.dumps({'etapas': [{'agente': 'pc', 'instrucao': 'crie a pasta Estudos'}, {'agente': 'tarefas', 'instrucao': 'estudar python amanhã às 9h'}]})
            else:
                out = 'ok, entendi'
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=Msg(out))])
    openai.OpenAI = Client
    sys.modules['openai'] = openai
    et = types.ModuleType('edge_tts')
    class Comm:
        def __init__(s, **k): pass
        async def save(s, fn): open(fn, 'wb').write(b'mp3')
    et.Communicate = Comm
    sys.modules['edge_tts'] = et


class FakeGateway:
    def __init__(s): s.sent = []
    def post(s, url, json=None, headers=None, timeout=None, **k):
        s.sent.append((json['action'], json.get('params'))); r = mock.Mock(status_code=200)
        r.json.return_value = {'ok': True, 'command_id': f'c{len(s.sent)}'}; return r
    def get(s, url, headers=None, timeout=None, params=None, **k):
        r = mock.Mock(status_code=200)
        if url.endswith('/agent/results'):
            r.json.return_value = {'results': [{'command_id': f'c{i + 1}', 'result': {'ok': True, 'message': f'{a} feito'}} for i, (a, _) in enumerate(s.sent)]}
        else:
            r.json.return_value = {'ok': True, 'online': True, 'age_seconds': 2, 'info': {'computer': 'PC', 'cpu_percent': 10, 'ram_em_uso_percent': 40, 'rotinas_ativas': 1},
                                   'history': [], 'queued_commands': 0,
                                   'whatsapp': {'configured': False, 'missing': ['WHATSAPP_TOKEN'], 'allowed_count': 0, 'messages_today': 0, 'last_message_at': '', 'last_error': '', 'log': []}}
        return r


class TestAppSmoke(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd(); self._tmp = tempfile.TemporaryDirectory(); os.chdir(self._tmp.name)
        env = {'OPENROUTER_API_KEY': 'k', 'JARVIS_GATEWAY_URL': 'http://gw', 'LOCAL_AGENT_TOKEN': 'tok'}
        for k in ('SUPABASE_URL', 'SUPABASE_KEY', 'HONCHO_API_KEY'): os.environ.pop(k, None)
        mock.patch.dict(os.environ, env).start(); self.gw = FakeGateway()
        mock.patch('requests.post', self.gw.post).start(); mock.patch('requests.get', self.gw.get).start()
        self.state = SState(); self.addCleanup(mock.patch.stopall); self.addCleanup(os.chdir, self._old); self.addCleanup(self._tmp.cleanup)
        for m in ('app', 'core', 'store', 'agents'): sys.modules.pop(m, None)

    def run_app(self, prompt=None):
        st = build_streamlit(self.state, prompt); install_fakes(st)
        if 'core' in sys.modules: sys.modules['core'].tz  # noqa
        runpy.run_path(os.path.join(ROOT, 'app.py'), run_name='__main__')
        return st

    def last_answer(self): return [m for m in self.state.messages if m['role'] == 'assistant'][-1]['content']

    def test_initial_render_all_tabs(self):
        st = self.run_app(None); self.assertTrue(st.tabs.__class__)  # não levantou exceção
        self.assertEqual(self.state.messages, [])

    def test_team_command_in_chat(self):
        self.run_app('/equipe organize meus estudos de python')
        a = self.last_answer(); self.assertIn('Equipe Jarvis', a); self.assertIn('create_folder feito', a); self.assertIn('Tarefa #1 criada', a)
        self.assertEqual([c[0] for c in self.gw.sent], ['create_folder'])
        self.assertEqual(len(self.state.tasks), 1)                                     # sessão enxerga a tarefa criada pela equipe
        self.assertEqual(self.state.last_team['trace'][1]['agente'], 'tarefas')
        self.run_app(None)                                                             # aba Agentes renderiza com a última execução

    def test_task_created_with_sao_paulo_timezone(self):
        self.run_app('me lembre de pagar a conta amanhã às 10h'); t = self.state.tasks[0]
        self.assertTrue(t['due_at'].endswith('-03:00'), t['due_at']); self.assertIn('T10:00', t['due_at'])

    def test_delete_confirmation_flow_still_works(self):
        self.run_app('apague a pasta Velha'); self.assertIsNotNone(self.state.pending_pc); self.assertEqual(self.gw.sent, [])
        self.assertIn('Confirma', self.last_answer())
        self.run_app('sim'); self.assertEqual(self.gw.sent[0][0], 'delete_path'); self.assertTrue(self.gw.sent[0][1]['confirmed'])

    def test_state_refresh_picks_up_tasks_written_by_whatsapp(self):
        self.run_app(None); import core
        core.create_task('tarefa vinda do whatsapp'); self.run_app(None)
        self.assertEqual([t['text'] for t in self.state.tasks], ['tarefa vinda do whatsapp'])

    def test_read_failure_never_wipes_session_tasks(self):
        self.run_app('me lembre de algo importante'); self.assertEqual(len(self.state.tasks), 1)
        with mock.patch('store.load', side_effect=lambda k, d=None: d): self.run_app(None)   # store.load real nunca levanta: com Supabase fora e sem arquivo, devolve o default
        self.assertEqual(len(self.state.tasks), 1)


if __name__ == '__main__':
    unittest.main()
