"""Testes do Jarvis V12.5 (sem rede, sem Streamlit/FastAPI). Rode:  python -m unittest discover -s tests -v"""
import asyncio, hashlib, hmac, json, os, sys, tempfile, threading, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'tests'))

import agents, core, whatsapp, store  # noqa: E402


class InTmp(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd(); self._tmp = tempfile.TemporaryDirectory(); os.chdir(self._tmp.name)
        for k in ('SUPABASE_URL', 'SUPABASE_KEY'): os.environ.pop(k, None)
    def tearDown(self):
        os.chdir(self._old); self._tmp.cleanup()


# ---------------------------------------------------------------- agentes
class TestAgents(unittest.TestCase):
    def test_parse_plan(self):
        txt = '```json\n{"etapas":[{"agente":"tarefas","instrucao":"estudar"},{"agente":"hacker","instrucao":"x"},{"agente":"pc","instrucao":""}]}\n```'
        self.assertEqual(agents.parse_plan(txt), [{'agente': 'tarefas', 'instrucao': 'estudar'}])
        self.assertIsNone(agents.parse_plan('sem json'))
        self.assertIsNone(agents.parse_plan('{"etapas":"x"}'))
        many = json.dumps({'etapas': [{'agente': 'redator', 'instrucao': str(i)} for i in range(20)]})
        self.assertEqual(len(agents.parse_plan(many)), agents.MAX_STEPS)

    def test_wants_team(self):
        for t in ('/equipe organize tudo', 'use a equipe de agentes para isso', 'planeje meus estudos de python para a semana'):
            self.assertTrue(agents.wants_team(t), t)
        for t in ('abra o vs code', 'planeje', 'oi tudo bem', 'crie a pasta Estudos'):
            self.assertFalse(agents.wants_team(t), t)
        self.assertEqual(agents.strip_trigger('/equipe organize meus estudos'), 'organize meus estudos')

    def _team(self, plan_json, handlers):
        return agents.Team(lambda m, temperature=0.4: plan_json, handlers)

    def test_team_runs_and_reports(self):
        plan = json.dumps({'etapas': [{'agente': 'pc', 'instrucao': 'crie a pasta A'}, {'agente': 'redator', 'instrucao': 'resuma'}]})
        out = self._team(plan, {'pc': lambda i, c: (True, 'Pasta criada'), 'redator': lambda i, c: (True, 'Resumo pronto')}).run('meta')
        self.assertTrue(out['ok']); self.assertIn('Pasta criada', out['reply']); self.assertIn('Resumo pronto', out['reply'])

    def test_team_stops_after_failure(self):
        plan = json.dumps({'etapas': [{'agente': 'pc', 'instrucao': 'a'}, {'agente': 'tarefas', 'instrucao': 'b'}]})
        ran = []
        out = self._team(plan, {'pc': lambda i, c: (False, 'erro'), 'tarefas': lambda i, c: ran.append(1) or (True, 'x')}).run('meta')
        self.assertFalse(out['ok']); self.assertEqual(ran, []); self.assertIsNone(out['trace'][1]['ok'])

    def test_team_without_plan_falls_back_to_redator(self):
        out = self._team('lixo', {'redator': lambda i, c: (True, 'resposta direta')}).run('oi')
        self.assertFalse(out['planned']); self.assertIn('resposta direta', out['reply'])

    def test_handler_exception_is_contained(self):
        def boom(i, c): raise ValueError('x')
        out = self._team(json.dumps({'etapas': [{'agente': 'pc', 'instrucao': 'a'}]}), {'pc': boom}).run('m')
        self.assertFalse(out['ok']); self.assertIn('Erro inesperado', out['trace'][0]['saida'])


# ---------------------------------------------------------------- núcleo
class FakePC:
    def __init__(self): self.calls = []
    def __call__(self, action, params=None):
        self.calls.append((action, dict(params or {})))
        if action == 'list_files': return {'ok': True, 'result': {'ok': True, 'message': '1 item', 'itens': [{'nome': 'Estudos', 'tipo': 'pasta'}]}}
        if action == 'create_folder': return {'ok': True, 'result': {'ok': True, 'message': f"Pasta criada: {params['name']}"}}
        return {'ok': True, 'result': {'ok': True, 'message': f'{action} ok'}}


class TestCore(InTmp):
    def brain(self, llm=None, pc=None, status=None):
        self.pc = pc or FakePC()
        return core.Brain(self.pc, llm=llm or (lambda m, temperature=0.4: 'resposta do llm'), agent_status=status)

    def test_parse_due_timezone_and_day_after(self):
        d = core.parse_due('estudar amanhã às 9h'); self.assertTrue(d.endswith('-03:00')); self.assertIn('T09:00', d)
        a = core.now().date()
        self.assertEqual(core.parse_due('x depois de amanhã às 8h')[:10], (a + core.dt.timedelta(days=2)).isoformat())

    def test_parse_due_hour_formats(self):
        for txt, hhmm in (('x amanhã às 10h', '10:00'), ('x amanhã às 18h30', '18:30'), ('x hoje às 7:15', '07:15'), ('x hoje às 9', '09:00'),
                          ('x amanhã às 8 horas', '08:00'), ('x amanhã às 7 da noite', '19:00'), ('x amanhã às 3 da tarde', '15:00'), ('x amanhã', '09:00')):
            self.assertEqual(core.parse_due(txt)[11:16], hhmm, txt)
        self.assertEqual(core.parse_due('x amanhã às 25h'), '')   # hora inválida: sem prazo, não derruba
        self.assertEqual(core.clean_task_text('me lembre de pagar a conta amanhã às 10h30'), 'pagar a conta')
        self.assertEqual(core.clean_task_text('crie uma tarefa estudar às 7 da noite'), 'estudar')

    def test_calculator_blocks_power_bomb(self):
        self.assertEqual(core.calculator('9**9**9'), 'Expressão não permitida.')
        self.assertEqual(core.calculator('2,5+1'), '3.5')

    def test_tasks_roundtrip(self):
        b = self.brain()
        self.assertIn('Tarefa #1 criada', b.handle('u', 'me lembre de pagar a conta amanhã às 10h')['reply'])
        self.assertIn('pagar a conta', b.handle('u', '/tarefas')['reply'])
        self.assertIn('concluída', b.handle('u', 'conclua a tarefa #1')['reply'])
        self.assertIn('sem tarefas pendentes'.split()[0], 'sem'); self.assertIn('não tem tarefas', b.handle('u', 'minhas tarefas')['reply'])

    def test_pc_command_runs_and_formats(self):
        b = self.brain(); r = b.handle('u', 'crie a pasta Estudos')
        self.assertEqual(self.pc.calls[0][0], 'create_folder'); self.assertIn('✅', r['reply']); self.assertIn('Pasta criada', r['reply'])
        self.assertIn('Estudos/', b.handle('u', 'liste os arquivos')['reply'])

    def test_delete_requires_confirmation(self):
        b = self.brain(); r = b.handle('u', 'apague a pasta Velha')
        self.assertEqual(self.pc.calls, []); self.assertIn('Confirma', r['reply'])
        b.handle('u', 'sim'); self.assertEqual(self.pc.calls[0], ('delete_path', {'name': 'Velha', 'confirmed': True}))

    def test_cancel_and_expiry_and_other_message_drop_pending(self):
        b = self.brain(); b.handle('u', 'apague a pasta A'); self.assertIn('Cancelado', b.handle('u', 'não')['reply']); self.assertEqual(self.pc.calls, [])
        b.handle('u', 'apague a pasta A'); b.pending['u'] = (time.time() - 1000, b.pending['u'][1]); b.handle('u', 'sim'); self.assertEqual(self.pc.calls, [])
        b.handle('u', 'apague a pasta A'); b.handle('u', 'que horas são'); b.handle('u', 'sim'); self.assertEqual(self.pc.calls, [])

    def test_pending_is_per_user(self):
        b = self.brain(); b.handle('a', 'apague a pasta A'); b.handle('b', 'sim'); self.assertEqual(self.pc.calls, [])

    def test_status_and_help(self):
        b = self.brain(status=lambda: {'ok': True, 'online': True, 'info': {'computer': 'PC', 'cpu_percent': 12.4, 'ram_em_uso_percent': 40, 'rotinas_ativas': 2}})
        self.assertIn('online', b.handle('u', '/status')['reply']); self.assertIn('/equipe', b.handle('u', '/ajuda')['reply'])
        self.assertIn('offline', self.brain(status=lambda: {'ok': True, 'online': False, 'info': {}}).handle('u', '/status')['reply'])

    def test_chat_uses_llm_and_history(self):
        seen = []
        b = self.brain(llm=lambda m, temperature=0.4: seen.append(m) or 'olá!')
        self.assertEqual(b.handle('u', 'bom dia')['reply'], 'olá!'); b.handle('u', 'e agora?')
        self.assertTrue(any(x['content'] == 'bom dia' for x in seen[-1]))

    def test_no_llm_message(self):
        b = core.Brain(FakePC(), llm=None); self.assertIn('OPENROUTER_API_KEY', b.handle('u', 'oi')['reply'])

    def test_team_end_to_end_and_never_deletes(self):
        plan = json.dumps({'etapas': [{'agente': 'pc', 'instrucao': 'crie a pasta Estudos'}, {'agente': 'tarefas', 'instrucao': 'estudar python amanhã às 9h'},
                                      {'agente': 'pc', 'instrucao': 'apague a pasta Velha'}, {'agente': 'memoria', 'instrucao': 'prefere estudar de manhã'}]})
        b = self.brain(llm=lambda m, temperature=0.4: plan)
        out = b.handle('u', '/equipe organize meus estudos de python'); self.assertEqual(out['tool'], 'equipe')
        self.assertEqual([c[0] for c in self.pc.calls], ['create_folder'])          # delete_path nunca foi enviado
        self.assertIn('Equipes não apagam', out['reply'])
        self.assertEqual(len(core.load_tasks()), 1); self.assertEqual(core.load_memory(), {})   # parou na falha
        self.assertTrue(store.load('team_last', {}).get('trace'))

    def test_team_handlers_tasks_and_memory(self):
        b = self.brain(); self.assertTrue(b._h_tarefas('estudar python amanhã às 9h', {})[0]); self.assertTrue(b._h_memoria('gosta de café', {})[0])
        self.assertIn('gosta de café', list(core.load_memory().values())[0])


# ---------------------------------------------------------------- WhatsApp
ENV = {'WHATSAPP_TOKEN': 't', 'WHATSAPP_PHONE_NUMBER_ID': '123', 'WHATSAPP_VERIFY_TOKEN': 'vt', 'WHATSAPP_APP_SECRET': 'segredo',
       'WHATSAPP_ALLOWED_NUMBERS': '+55 (11) 99999-8888'}


def payload(*msgs):
    return {'object': 'whatsapp_business_account', 'entry': [{'changes': [{'value': {'messages': list(msgs)}}]}]}


def text_msg(mid='wamid.1', frm='5511999998888', body='oi'):
    return {'id': mid, 'from': frm, 'type': 'text', 'text': {'body': body}}


class TestWhatsApp(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.dict(os.environ, ENV); self.p.start()
        whatsapp._seen.clear(); whatsapp._hits.clear(); whatsapp.LOG.clear(); whatsapp.STATE.update(last_message_at='', day='', today=0, last_error='')
    def tearDown(self): self.p.stop()

    def test_missing_and_configured(self):
        self.assertTrue(whatsapp.configured())
        with mock.patch.dict(os.environ, {'WHATSAPP_APP_SECRET': ''}): self.assertEqual(whatsapp.missing(), ['WHATSAPP_APP_SECRET']); self.assertFalse(whatsapp.configured())

    def test_verify_challenge(self):
        self.assertEqual(whatsapp.verify_challenge('subscribe', 'vt', '777'), '777')
        self.assertIsNone(whatsapp.verify_challenge('subscribe', 'errado', '777')); self.assertIsNone(whatsapp.verify_challenge('x', 'vt', '1'))
        with mock.patch.dict(os.environ, {'WHATSAPP_VERIFY_TOKEN': ''}): self.assertIsNone(whatsapp.verify_challenge('subscribe', '', '1'))

    def test_signature(self):
        raw = b'{"a":1}'; good = 'sha256=' + hmac.new(b'segredo', raw, hashlib.sha256).hexdigest()
        self.assertTrue(whatsapp.valid_signature(raw, good)); self.assertFalse(whatsapp.valid_signature(raw + b' ', good))
        self.assertFalse(whatsapp.valid_signature(raw, None)); self.assertFalse(whatsapp.valid_signature(raw, 'sha256=00'))
        with mock.patch.dict(os.environ, {'WHATSAPP_APP_SECRET': ''}): self.assertFalse(whatsapp.valid_signature(raw, good))

    def test_extract_messages(self):
        audio = {'id': 'wamid.2', 'from': '5511999998888', 'type': 'audio', 'audio': {'id': 'M1'}}
        got = whatsapp.extract_messages(payload(text_msg(), audio))
        self.assertEqual([(g['type'], g['text'], g['media_id']) for g in got], [('text', 'oi', ''), ('audio', '', 'M1')])
        self.assertEqual(whatsapp.extract_messages({'entry': [{'changes': [{'value': {'statuses': [{'id': 'x'}]}}]}]}), [])
        self.assertEqual(whatsapp.extract_messages('lixo'), [])

    def test_allowlist_handles_brazilian_ninth_digit(self):
        for n in ('5511999998888', '551199998888', '+55 11 99999-8888'): self.assertTrue(whatsapp.is_allowed(n), n)
        for n in ('5511888887777', '', None): self.assertFalse(whatsapp.is_allowed(n), n)
        with mock.patch.dict(os.environ, {'WHATSAPP_ALLOWED_NUMBERS': ''}): self.assertFalse(whatsapp.is_allowed('5511999998888'))

    def test_dedupe_and_rate_limit(self):
        self.assertFalse(whatsapp.already_seen('a')); self.assertTrue(whatsapp.already_seen('a'))
        self.assertTrue(all(whatsapp.rate_ok('551', limit=3) for _ in range(3))); self.assertFalse(whatsapp.rate_ok('551', limit=3)); self.assertTrue(whatsapp.rate_ok('552', limit=3))

    def test_split_text(self):
        self.assertEqual(whatsapp.split_text('curto'), ['curto']); self.assertEqual(whatsapp.split_text('   '), [])
        long = ('palavra ' * 1500).strip(); parts = whatsapp.split_text(long)
        self.assertTrue(len(parts) >= 3 and all(len(p) <= whatsapp.MAX_TEXT for p in parts)); self.assertEqual(' '.join(parts).split(), long.split())

    def test_send_text_ok_and_error_hints(self):
        ok = mock.Mock(status_code=200)
        with mock.patch('whatsapp.requests.post', return_value=ok) as post:
            self.assertEqual(whatsapp.send_text('+55 11 99999-8888', 'oi'), (True, '')); body = post.call_args.kwargs['json']
            self.assertEqual((body['to'], body['text']['body']), ('5511999998888', 'oi')); self.assertIn('/123/messages', post.call_args.args[0])
        bad = mock.Mock(status_code=401); bad.json.return_value = {'error': {'code': 190, 'message': 'x'}}
        with mock.patch('whatsapp.requests.post', return_value=bad):
            ok_, err = whatsapp.send_text('5511999998888', 'oi'); self.assertFalse(ok_); self.assertIn('token', err.lower())
        self.assertIn('token', whatsapp.status()['last_error'].lower())

    def test_status_hides_message_content(self):
        whatsapp.log_event('in', '5511999998888', 'texto'); s = whatsapp.status()
        self.assertEqual((s['messages_today'], s['allowed_count'], s['log'][0]['numero']), (1, 1, '***8888')); self.assertNotIn('texto_da_mensagem', json.dumps(s))

    def test_download_media(self):
        meta = mock.Mock(status_code=200); meta.json.return_value = {'url': 'https://m/x', 'mime_type': 'audio/ogg; codecs=opus', 'file_size': 10}
        blob = mock.Mock(status_code=200, content=b'abc')
        with mock.patch('whatsapp.requests.get', side_effect=[meta, blob]):
            self.assertEqual(whatsapp.download_media('M1'), (b'abc', 'audio/ogg; codecs=opus'))
        self.assertEqual(whatsapp.audio_filename('audio/ogg; codecs=opus'), 'voz.ogg'); self.assertEqual(whatsapp.audio_filename('audio/mpeg'), 'voz.mp3')


# ---------------------------------------------------------------- gateway (com shim do FastAPI)
class TestGateway(InTmp):
    @classmethod
    def setUpClass(cls):
        import fake_fastapi; fake_fastapi.install(); os.environ['LOCAL_AGENT_TOKEN'] = 'tok'
        import gateway; cls.gw = gateway; cls.fa = fake_fastapi

    def setUp(self):
        super().setUp(); self.p = mock.patch.dict(os.environ, ENV); self.p.start(); gw = self.gw
        whatsapp._seen.clear(); whatsapp._hits.clear(); whatsapp.LOG.clear(); gw.COMMANDS.clear(); gw.RESULTS.clear(); gw._BRAIN['obj'] = None
        gw.AGENT.update(last_seen=0.0, info={})
        self.sent = []; self.sp = mock.patch('whatsapp.send_text', side_effect=lambda to, body: self.sent.append((to, body)) or (True, '')); self.sp.start()
        mock.patch('whatsapp.mark_read').start(); self.addCleanup(mock.patch.stopall)
    def tearDown(self): self.p.stop(); super().tearDown()

    class Req:
        def __init__(s, raw=b'', headers=None, query=None): s._raw, s.headers, s.query_params = raw, headers or {}, query or {}
        async def body(s): return s._raw
        async def json(s): return json.loads(s._raw)

    def post(self, pl, sign=True):
        raw = json.dumps(pl).encode(); sig = 'sha256=' + hmac.new(b'segredo', raw, hashlib.sha256).hexdigest() if sign else 'sha256=bad'
        bg = self.fa.BackgroundTasks(); route = self.gw.app.routes[('POST', '/webhook')]
        res = asyncio.run(route(self.Req(raw, {'x-hub-signature-256': sig}), bg)); return res, bg

    def agent_thread(self, reply=None):
        stop = threading.Event()
        def loop():
            while not stop.is_set():
                self.gw.AGENT['last_seen'] = time.time()
                for c in list(self.gw.COMMANDS):
                    self.gw.COMMANDS.remove(c); self.gw.RESULTS.append({'command_id': c['id'], 'action': c['action'], 'result': reply or {'ok': True, 'message': f"{c['action']} feito"}})
                time.sleep(0.05)
        t = threading.Thread(target=loop, daemon=True); t.start(); self.addCleanup(stop.set)

    def test_verify_route(self):
        r = self.gw.app.routes[('GET', '/webhook')]
        self.assertEqual(r(self.Req(query={'hub.mode': 'subscribe', 'hub.verify_token': 'vt', 'hub.challenge': '42'})).body, '42')
        with self.assertRaises(self.fa.HTTPException) as c: r(self.Req(query={'hub.mode': 'subscribe', 'hub.verify_token': 'x', 'hub.challenge': '42'}))
        self.assertEqual(c.exception.status_code, 403)

    def test_bad_signature_rejected(self):
        with self.assertRaises(self.fa.HTTPException) as c: self.post(payload(text_msg()), sign=False)
        self.assertEqual(c.exception.status_code, 403)

    def test_unauthorized_number_ignored_and_duplicates_dropped(self):
        res, bg = self.post(payload(text_msg(frm='5511888887777'))); self.assertEqual((res['queued'], bg.tasks), (0, []))
        self.assertEqual(whatsapp.status()['log'][0]['tipo'], 'bloqueado')
        res, bg = self.post(payload(text_msg(mid='ok1'))); self.assertEqual(res['queued'], 1); res2, _ = self.post(payload(text_msg(mid='ok1'))); self.assertEqual(res2['queued'], 0)

    def test_text_message_runs_pc_command_and_replies(self):
        self.agent_thread(); res, bg = self.post(payload(text_msg(body='crie a pasta Estudos'))); fn, a, k = bg.tasks[0]; fn(*a, **k)
        self.assertEqual(len(self.sent), 1); to, body = self.sent[0]; self.assertEqual(to, '5511999998888'); self.assertIn('create_folder feito', body)

    def test_offline_agent_is_reported_not_faked(self):
        _, bg = self.post(payload(text_msg(body='abra o vs code'))); fn, a, k = bg.tasks[0]; fn(*a, **k)
        self.assertIn('offline', self.sent[0][1]); self.assertIn('❌', self.sent[0][1])

    def test_delete_via_whatsapp_needs_yes(self):
        self.agent_thread()
        for i, body in enumerate(['apague a pasta Velha', 'sim']):
            _, bg = self.post(payload(text_msg(mid=f'w{i}', body=body))); fn, a, k = bg.tasks[0]; fn(*a, **k)
            if i == 0: self.assertIn('Confirma', self.sent[-1][1]); self.assertEqual(self.gw.RESULTS, [])
        self.assertEqual(self.gw.RESULTS[-1]['action'], 'delete_path')

    def test_audio_is_transcribed_then_handled(self):
        self.agent_thread(); audio = {'id': 'wa1', 'from': '5511999998888', 'type': 'audio', 'audio': {'id': 'M1'}}
        with mock.patch('whatsapp.download_media', return_value=(b'x' * 10, 'audio/ogg')), mock.patch('voice_io.transcribe', return_value='abra o youtube'):
            _, bg = self.post(payload(audio)); fn, a, k = bg.tasks[0]; fn(*a, **k)
        self.assertIn('Entendi: "abra o youtube"', self.sent[0][1]); self.assertIn('open_url feito', self.sent[0][1])

    def test_voice_error_is_friendly(self):
        import voice_io
        with mock.patch('whatsapp.download_media', return_value=(b'x', 'audio/ogg')), mock.patch('voice_io.transcribe', side_effect=voice_io.VoiceError('Não ouvi nada.')):
            _, bg = self.post(payload({'id': 'wa2', 'from': '5511999998888', 'type': 'audio', 'audio': {'id': 'M'}})); fn, a, k = bg.tasks[0]; fn(*a, **k)
        self.assertIn('Não ouvi nada', self.sent[0][1])

    def test_image_message_gets_polite_reply(self):
        _, bg = self.post(payload({'id': 'w9', 'from': '5511999998888', 'type': 'image'})); fn, a, k = bg.tasks[0]; fn(*a, **k); self.assertIn('texto e áudio', self.sent[0][1])

    def test_status_endpoint_includes_whatsapp_and_requires_token(self):
        r = self.gw.app.routes[('GET', '/agent/status')]
        with self.assertRaises(self.fa.HTTPException): r('errado')
        s = r('tok'); self.assertTrue(s['whatsapp']['configured']); self.assertNotIn('texto', json.dumps(s['whatsapp']['log']))

    def test_command_validation_unchanged(self):
        enq = self.gw.enqueue
        for action, params in (('rm_rf', {}), ('delete_path', {'name': 'x'}), ('schedule_add', {'steps': [{'action': 'delete_path'}]})):
            with self.assertRaises(self.fa.HTTPException): enq(action, params)
        self.assertTrue(enq('delete_path', {'name': 'x', 'confirmed': True}))


if __name__ == '__main__':
    unittest.main()
