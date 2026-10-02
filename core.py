"""Jarvis V12.6 - núcleo sem Streamlit.

Usado pelo canal WhatsApp (no gateway) e pela equipe de agentes (no app).
Guarda tarefas e memória no mesmo `store` do app: com Supabase configurado nos DOIS serviços
do Render, WhatsApp e site enxergam as mesmas tarefas e memórias.
"""
import datetime as dt
import json
import os
import re
import time
import unicodedata

import agents
import store
from agents import wants_team, strip_trigger
from pc_control import parse_pc_commands, CONFIRM_ACTIONS, describe_step, is_confirm, is_cancel

PENDING_TTL = 300          # segundos para responder "sim/não" a uma confirmação


# ------------------------------------------------------------------ tempo
def tz():
    """Fuso do usuário (o Render roda em UTC). Brasil não tem horário de verão desde 2019."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.getenv('JARVIS_TZ', 'America/Sao_Paulo'))
    except Exception:
        return dt.timezone(dt.timedelta(hours=-3))


def now():
    return dt.datetime.now(tz())


def current_time():
    return now().strftime('%d/%m/%Y %H:%M:%S')


def iso_now():
    return now().isoformat(timespec='seconds')


def _norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s).lower()) if unicodedata.category(c) != 'Mn')


# ------------------------------------------------------------------ utilidades de texto
def calculator(expr):
    expr = (expr or '').strip()
    if not expr or any(c not in '0123456789+-*/().,% ' for c in expr) or '**' in expr:
        return 'Expressão não permitida.'
    try:
        return str(eval(expr.replace(',', '.').replace('%', '/100'), {'__builtins__': {}}, {}))
    except Exception as e:
        return f'Erro no cálculo: {e}'


# "às 10", "às 10h", "às 10h30", "às 10:30", "às 10 horas" (e "a 10h30" sem acento)
_HOUR = r'\b(?:às|as)\s*(\d{1,2})(?:[:h](\d{2})?|\s*horas?)?(?![\d:])'
_HOUR_A = r'\ba\s*(\d{1,2})[:h](\d{2})?(?![\d:])'


def parse_due(text):
    """Extrai data/hora simples em PT-BR (no fuso do usuário). Retorna ISO com fuso ou ''."""
    s = text.lower()
    base = now()
    hour = None
    m = re.search(_HOUR, s) or re.search(_HOUR_A, s)
    if m:
        hour = (int(m.group(1)), int(m.group(2) or 0))
        if re.match(r'\s+da\s+(?:tarde|noite)\b', s[m.end():]) and hour[0] < 12:
            hour = (hour[0] + 12, hour[1])
    if 'hoje' in s:
        d = base.date()
    elif 'depois de amanhã' in s or 'depois de amanha' in s:
        d = (base + dt.timedelta(days=2)).date()
    elif 'amanhã' in s or 'amanha' in s:
        d = (base + dt.timedelta(days=1)).date()
    else:
        m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', s)
        if m:
            y = int(m.group(3) or base.year)
            y += 2000 if y < 100 else 0
            try:
                d = dt.date(y, int(m.group(2)), int(m.group(1)))
            except ValueError:
                d = None
        else:
            d = None
    if d is None:
        return ''
    h, mi = hour or (9, 0)
    try:
        return dt.datetime.combine(d, dt.time(h, mi), tzinfo=tz()).isoformat(timespec='minutes')
    except ValueError:
        return ''


def recurrence_from_text(text):
    s = text.lower()
    if 'todo dia' in s or 'diariamente' in s:
        return 'daily'
    for words, val in ((('todo sábado', 'todo sabado'), 'saturday'), (('todo domingo',), 'sunday'),
                       (('toda segunda',), 'monday'), (('toda terça', 'toda terca'), 'tuesday'),
                       (('toda quarta',), 'wednesday'), (('toda quinta',), 'thursday'), (('toda sexta',), 'friday')):
        if any(w in s for w in words):
            return 'weekly:' + val
    return ''


def clean_task_text(text):
    c = text.strip()
    for p in ['crie uma tarefa', 'adiciona uma tarefa', 'adicione uma tarefa', 'nova tarefa', 'criar tarefa',
              'me lembre de', 'lembre de']:
        c = re.sub(re.escape(p), '', c, flags=re.I)
    c = re.sub(r'\b(?:hoje|amanhã|amanha|depois de amanhã|depois de amanha)\b', '', c, flags=re.I)
    c = re.sub(_HOUR + r'(?:\s+da\s+(?:manhã|manha|tarde|noite))?', '', c, flags=re.I)
    c = re.sub(_HOUR_A, '', c, flags=re.I)
    c = re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', '', c)
    return re.sub(r'\s+', ' ', c).strip(' .,-') or 'Tarefa sem título'


# ------------------------------------------------------------------ tarefas e memória (no store)
def load_tasks():
    d = store.load('tasks', [])
    return d if isinstance(d, list) else []


def load_memory():
    d = store.load('memory', {})
    return d if isinstance(d, dict) else {}


def create_task(text, priority='normal', due=None, recurrence=''):
    tasks = load_tasks()
    t = {'id': max([int(x.get('id', 0)) for x in tasks] or [0]) + 1, 'text': clean_task_text(text), 'priority': priority,
         'status': 'pending', 'created_at': iso_now(), 'due_at': due or '', 'recurrence': recurrence, 'completed_at': ''}
    tasks.append(t)
    store.save('tasks', tasks)
    return t


def complete_task(task_id):
    tasks = load_tasks()
    for t in tasks:
        if int(t.get('id', -1)) == int(task_id):
            t['status'], t['completed_at'] = 'done', iso_now()
            store.save('tasks', tasks)
            return t
    return None


def delete_task(task_id):
    tasks = load_tasks()
    keep = [t for t in tasks if int(t.get('id', -1)) != int(task_id)]
    if len(keep) == len(tasks):
        return False
    store.save('tasks', keep)
    return True


def task_is_overdue(t):
    try:
        return t.get('status') != 'done' and bool(t.get('due_at')) and dt.datetime.fromisoformat(t['due_at']) < now()
    except Exception:
        return False


def pending_tasks(tasks=None):
    ts = [t for t in (load_tasks() if tasks is None else tasks) if t.get('status') != 'done']
    return sorted(ts, key=lambda x: x.get('due_at') or '9999')


def tasks_text(limit=15):
    ts = pending_tasks()
    if not ts:
        return 'Você não tem tarefas pendentes. 🎉'
    lines = []
    for t in ts[:limit]:
        due = ''
        if t.get('due_at'):
            try:
                due = ' — ' + dt.datetime.fromisoformat(t['due_at']).strftime('%d/%m %H:%M')
            except Exception:
                pass
        lines.append(f"#{t['id']} {t['text']}{due}{' ⚠️ atrasada' if task_is_overdue(t) else ''}")
    more = f'\n(+{len(ts) - limit} outras)' if len(ts) > limit else ''
    return f'📋 {len(ts)} tarefa(s) pendente(s):\n' + '\n'.join(lines) + more


def save_memory_item(key, value):
    mem = load_memory()
    mem[str(key)] = str(value)
    store.save('memory', mem)
    return f'Memória salva: {value}'


def web_search(query):
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get('https://www.google.com/search', params={'q': query}, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        out = []
        for b in soup.select('div'):
            x = b.get_text(' ', strip=True)
            if 80 < len(x) < 400 and x not in out:
                out.append(x)
            if len(out) >= 5:
                break
        return '\n'.join(out) or 'Nenhum resultado resumível encontrado.'
    except Exception as e:
        return f'Erro na pesquisa: {type(e).__name__}'


TASK_TRIGGERS = ['crie uma tarefa', 'adiciona uma tarefa', 'adicione uma tarefa', 'nova tarefa', 'criar tarefa', 'me lembre de', 'lembre de']


def choose_tool(text):
    l = text.lower()
    if any(x in l for x in ['quanto é', 'calcule', 'calcular']):
        return 'calculator'
    if any(x in l for x in ['que horas', 'horário', 'horario', 'data de hoje']):
        return 'time'
    if any(x in l for x in TASK_TRIGGERS):
        return 'task'
    if any(x in l for x in ['conclua a tarefa', 'concluir tarefa', 'finalize a tarefa', 'marque a tarefa']):
        return 'complete_task'
    if any(x in l for x in ['apague a tarefa', 'exclua a tarefa', 'delete a tarefa']):
        return 'delete_task'
    if any(x in l for x in ['lembra de', 'guarde que', 'memorize']):
        return 'memory'
    if any(x in l for x in ['pesquise', 'procure na internet', 'pesquisa na web']):
        return 'web'
    return None


def _task_id(text):
    m = re.search(r'(?:tarefa\s*#?|#)(\d+)', text.lower())
    return int(m.group(1)) if m else None


def make_task_from_text(text):
    low = text.lower()
    priority = 'high' if any(x in low for x in ['alta prioridade', 'urgente', 'urgência']) else ('low' if 'baixa prioridade' in low else 'normal')
    due = parse_due(text)
    t = create_task(text, priority, due, recurrence_from_text(text))
    when = f" • prazo: {dt.datetime.fromisoformat(due).strftime('%d/%m/%Y %H:%M')}" if due else ''
    rec = f" • recorrência: {t['recurrence']}" if t['recurrence'] else ''
    return t, f"Tarefa #{t['id']} criada: {t['text']}{when}{rec}"


def memory_from_text(text):
    c = text
    for p in ['lembra de', 'guarde que', 'memorize']:
        c = re.sub(re.escape(p), '', c, count=1, flags=re.I)
    c = c.strip(' .:,-')
    return save_memory_item(f'memoria_{len(load_memory()) + 1}', c) if c else 'O que devo guardar?'


def execute_tool(text, tool=None):
    """Ferramentas simples e determinísticas. Retorna (tool, resultado) ou (None, None)."""
    tool = tool or choose_tool(text)
    if tool == 'calculator':
        e = text.lower()
        for p in ['quanto é', 'calcule', 'calcular']:
            e = e.replace(p, '')
        return tool, calculator(e.strip(' ?'))
    if tool == 'time':
        return tool, current_time()
    if tool == 'task':
        return tool, make_task_from_text(text)[1]
    if tool == 'complete_task':
        tid = _task_id(text)
        return tool, (f'Tarefa #{tid} concluída.' if tid and complete_task(tid) else 'Informe o número, por exemplo: conclua a tarefa #3.')
    if tool == 'delete_task':
        tid = _task_id(text)
        return tool, (f'Tarefa #{tid} excluída.' if tid and delete_task(tid) else 'Informe o número, por exemplo: apague a tarefa #3.')
    if tool == 'memory':
        return tool, memory_from_text(text)
    return None, None


# ------------------------------------------------------------------ LLM
def make_llm():
    """Cria fn(messages, temperature) -> str usando a OpenRouter. None se não houver OPENROUTER_API_KEY."""
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    if not key:
        return None
    model = os.getenv('OPENROUTER_MODEL', 'openai/gpt-oss-120b')
    from openai import OpenAI
    client = OpenAI(base_url='https://openrouter.ai/api/v1', api_key=key, timeout=45)

    def llm(messages, temperature=0.4):
        r = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
        return r.choices[0].message.content or ''
    return llm


# ------------------------------------------------------------------ formatação de resultados do PC
def _fmt_result(r):
    if not isinstance(r, dict):
        return str(r or '')
    msg = r.get('message') or r.get('error') or ''
    if r.get('content') is not None:
        msg += '\n' + str(r['content'])[:1200] + ('…' if r.get('truncated') else '')
    if r.get('itens'):
        msg += '\n' + '\n'.join(f"• {i['nome']}{'/' if i.get('tipo') == 'pasta' else ''}" for i in r['itens'][:30])
    if r.get('rotinas'):
        msg += '\n' + '\n'.join(f"#{x['id']} {x['quando']} — {x['o_que_faz']} ({'ativa' if x['ativa'] else 'pausada'}; próxima {x['proxima']})"
                                for x in r['rotinas'][:15])
    if r.get('ram_total_gb') is not None:
        msg += (f"\n💻 {r.get('computer', '?')} · {r.get('os', '')}\n🧠 RAM {r.get('ram_livre_gb', '?')}/{r.get('ram_total_gb')} GB livres"
                f"\n💾 Disco {r.get('disco_livre_gb', '?')}/{r.get('disco_total_gb', '?')} GB livres" + (f"\n⏱️ Ligado há {r['ligado_ha']}" if r.get('ligado_ha') else ''))
    return msg.strip()


def format_done(done):
    return '\n\n'.join(f"{'✅' if d['ok'] else '❌'} {d['acao']}\n{_fmt_result(d.get('resultado'))}".strip() for d in done)


def format_status(s):
    if not s or not s.get('ok', True):
        return '⚠️ ' + str((s or {}).get('error') or 'Sem status do agente.')
    info = s.get('info') or {}
    if not s.get('online'):
        return '🔴 Agente do PC offline. Abra o start_agent.bat no computador.'
    pr = info.get('proxima_rotina')
    cpu = info.get('cpu_percent')
    return (f"🟢 Agente online — {info.get('computer', '?')}\n"
            f"CPU {round(cpu) if cpu is not None else '—'}% · RAM {info.get('ram_em_uso_percent', '—')}% · disco livre {info.get('disco_livre_gb', '—')} GB\n"
            f"Rotinas ativas: {info.get('rotinas_ativas', '—')}" + (f" · próxima {pr['quando']}" if isinstance(pr, dict) else ''))


HELP = ('🤖 Jarvis no WhatsApp\n\n'
        '• abra o vs code · abra o youtube · crie a pasta Estudos\n'
        '• liste os arquivos · leia o arquivo notas.txt\n'
        '• todo dia às 9h abra o vs code (rotinas)\n'
        '• me lembre de pagar a conta amanhã às 10h\n'
        '• /tarefas · /rotinas · /status\n'
        '• /equipe <objetivo> — vários agentes trabalham juntos\n'
        '• apagar pede confirmação: responda sim ou não\n'
        '🎤 Pode mandar áudio também.')


# ------------------------------------------------------------------ o cérebro
class Brain:
    """Processa uma mensagem e devolve {'reply','tool'}. Não conhece Streamlit nem FastAPI.

    run_pc(action, params) -> {'ok','result'|'error'}     executa ação no PC (via agente local)
    llm(messages, temperature) -> str                     conversa (pode ser None)
    agent_status() -> {'ok','online','info'}              opcional, para /status
    """

    def __init__(self, run_pc, llm=None, agent_status=None, channel='whatsapp'):
        self.run_pc, self.llm, self.agent_status, self.channel = run_pc, llm, agent_status, channel
        self.pending = {}
        self.team = agents.Team(self._llm, {'pc': self._h_pc, 'tarefas': self._h_tarefas, 'memoria': self._h_memoria,
                                           'pesquisa': self._h_pesquisa, 'redator': self._h_redator})

    # ---- LLM
    def _llm(self, messages, temperature=0.4):
        if not self.llm:
            raise RuntimeError('OPENROUTER_API_KEY não configurada.')
        return self.llm(messages, temperature=temperature)

    def system_prompt(self, tool_result=''):
        mem, pend = load_memory(), pending_tasks()[:25]
        hint = ('Você está respondendo pelo WhatsApp: seja breve (até ~6 linhas), sem títulos nem tabelas; pode usar *negrito* e emojis com moderação.'
                if self.channel == 'whatsapp' else '')
        return ('Você é Jarvis, assistente pessoal em português do Brasil. Seja direto, inteligente, útil e honesto. '
                'Não invente fatos; se algo estiver incerto, diga. Só diga que algo foi feito no PC se o resultado da ferramenta tiver ok=true. '
                f'{hint}\nData/hora agora: {current_time()}\nMemória: {json.dumps(mem, ensure_ascii=False)[:3000]}\n'
                f'Tarefas pendentes: {json.dumps(pend, ensure_ascii=False)[:3000]}\n'
                f'Últimas ações no PC: {json.dumps(store.load("pc_history", [])[-6:], ensure_ascii=False)}\n'
                f'Perfil do PC: {json.dumps(store.load("pc_profile", {}), ensure_ascii=False)}'
                + (f'\nResultado da ferramenta: {tool_result}' if tool_result else ''))

    # ---- histórico curto por usuário
    def _hist_key(self):
        return f'hist_{self.channel}'

    def _history(self, user):
        d = store.load(self._hist_key(), {})
        return (d.get(user) if isinstance(d, dict) else None) or []

    def _remember_turn(self, user, text, reply):
        try:
            d = store.load(self._hist_key(), {})
            d = d if isinstance(d, dict) else {}
            h = (d.get(user) or []) + [{'role': 'user', 'content': text[:1500]}, {'role': 'assistant', 'content': reply[:1500]}]
            d[user] = h[-12:]
            store.save(self._hist_key(), d)
        except Exception:
            pass

    # ---- PC
    def _exec(self, steps, user=None, confirmed=False):
        """Executa passos em ordem; para no primeiro erro. Com `user`, guarda exclusões para confirmar."""
        done = []
        for i, (action, params) in enumerate(steps):
            if action == 'schedule_invalid':
                done.append({'acao': 'agendar', 'ok': False, 'resultado': params.get('error')})
                return done, 'error'
            if action in CONFIRM_ACTIONS and not confirmed:
                if user is None:
                    return done, 'blocked'
                self.pending[user] = (time.time(), steps[i:])
                return done, 'confirm'
            p = dict(params)
            if action in CONFIRM_ACTIONS:
                p['confirmed'] = True
            r = self.run_pc(action, p)
            done.append({'acao': describe_step(action, params), 'ok': bool(r.get('ok')), 'resultado': r.get('result') or r.get('error')})
            if not r.get('ok'):
                return done, 'error'
        return done, 'ok'

    def _remember_pc(self, done):
        try:
            hist = store.load('pc_history', [])
            hist = hist if isinstance(hist, list) else []
            for d in done:
                if d['acao'] == 'listar rotinas' or d['acao'].startswith('read_log'):
                    continue
                hist.append({'quando': now().strftime('%d/%m %H:%M'), 'acao': d['acao'][:120], 'ok': bool(d['ok'])})
                r = d.get('resultado')
                if d['acao'].startswith('system_info') and d['ok'] and isinstance(r, dict):
                    store.save('pc_profile', {k: r[k] for k in ('computer', 'os', 'processor', 'cpu_threads', 'ram_total_gb', 'disco_total_gb') if k in r})
            store.save('pc_history', hist[-40:])
        except Exception:
            pass

    # ---- agentes da equipe
    def _h_pc(self, instr, ctx):
        steps = parse_pc_commands(instr)
        if not steps:
            return False, f'Não entendi como comando de PC: "{instr}".'
        done, status = self._exec(steps)
        self._remember_pc(done)
        if status == 'blocked':
            return False, 'Equipes não apagam nada. Peça a exclusão direto ao Jarvis (ele pede confirmação).'
        return status == 'ok', format_done(done)

    def _h_tarefas(self, instr, ctx):
        text = instr if choose_tool(instr) == 'task' else 'crie uma tarefa ' + instr
        return True, make_task_from_text(text)[1]

    def _h_memoria(self, instr, ctx):
        return True, memory_from_text('guarde que ' + instr)

    def _h_pesquisa(self, instr, ctx):
        res = web_search(instr)
        if res.startswith('Erro') or res.startswith('Nenhum'):
            return False, res
        try:
            return True, self._llm([{'role': 'system', 'content': 'Resuma em português, em até 6 linhas, usando só os trechos fornecidos. Se não bastarem, diga.'},
                                    {'role': 'user', 'content': f'Tema: {instr}\nTrechos:\n{res}'}], temperature=0.2)
        except Exception as e:
            return False, f'Não consegui resumir: {e}'

    def _h_redator(self, instr, ctx):
        prev = '\n'.join(f"- {t['agente']}: {t['saida'][:600]}" for t in ctx.get('trace', []) if t.get('ok'))
        try:
            return True, self._llm([{'role': 'system', 'content': self.system_prompt()},
                                    {'role': 'user', 'content': f"Objetivo geral: {ctx.get('goal', '')}\nResultados das etapas anteriores:\n{prev or '(nenhum)'}\n\nSua tarefa: {instr}"}]).strip()
        except Exception as e:
            return False, f'Não consegui escrever: {e}'

    def team_run(self, goal):
        out = self.team.run(goal)
        try:
            record = {'quando': now().strftime('%d/%m %H:%M'), **{k: out[k] for k in ('goal', 'planned', 'trace', 'ok')}}
            store.save('team_last', record)
            history = store.load('team_history', [])
            if not isinstance(history, list):
                history = []
            history.append(record)
            store.save('team_history', history[-30:])
        except Exception:
            pass
        return out

    # ---- roteamento
    def handle(self, user, text):
        user, text = str(user or 'user'), (text or '').strip()
        if not text:
            return {'reply': 'Não recebi nenhum texto.', 'tool': None}
        try:
            out = self._route(user, text)
        except Exception as e:
            out = {'reply': f'Tive um erro ao processar ({type(e).__name__}). Tente de novo.', 'tool': 'erro'}
        self._remember_turn(user, text, out['reply'])
        return out

    def _route(self, user, text):
        # 1) confirmação pendente
        pend = self.pending.pop(user, None)
        if pend and time.time() - pend[0] <= PENDING_TTL:
            if is_confirm(text):
                done, _ = self._exec(pend[1], user=user, confirmed=True)
                self._remember_pc(done)
                return {'reply': format_done(done), 'tool': 'computer'}
            if is_cancel(text):
                return {'reply': 'Cancelado. Nada foi executado.', 'tool': 'computer'}

        n = _norm(text).strip()
        # 2) comandos de barra e atalhos
        if n.startswith('/'):
            cmd, _, rest = text.partition(' ')
            cmd = _norm(cmd)
            if cmd in ('/ajuda', '/help', '/start', '/menu'):
                return {'reply': HELP, 'tool': 'ajuda'}
            if cmd == '/tarefas':
                return {'reply': tasks_text(), 'tool': 'tarefas'}
            if cmd == '/status':
                return {'reply': format_status(self.agent_status() if self.agent_status else None), 'tool': 'status'}
            if cmd == '/rotinas':
                text = 'liste minhas rotinas'
            elif cmd == '/equipe':
                if not rest.strip():
                    return {'reply': 'Diga o objetivo. Exemplo: /equipe organize meus estudos de python: crie a pasta Estudos e uma tarefa para amanhã às 9h', 'tool': 'equipe'}
                return self._team(rest.strip())
        elif re.match(r'^(?:minhas tarefas|liste (?:minhas )?tarefas|quais (?:sao )?(?:as )?(?:minhas )?tarefas|mostre (?:minhas )?tarefas)\b', n):
            return {'reply': tasks_text(), 'tool': 'tarefas'}

        # 3) equipe de agentes
        if wants_team(text):
            return self._team(strip_trigger(text))

        # 4) comandos do PC
        steps = parse_pc_commands(text)
        if steps:
            done, status = self._exec(steps, user=user)
            self._remember_pc(done)
            reply = format_done(done)
            if status == 'confirm':
                todo = ', '.join(describe_step(a, p) for a, p in self.pending[user][1] if a in CONFIRM_ACTIONS)
                reply = (reply + '\n\n' if reply else '') + f'⚠️ Confirma? {todo}\nResponda *sim* ou *não*. (Vai para a lixeira do Jarvis e dá para restaurar.)'
            return {'reply': reply or 'Nada a fazer.', 'tool': 'computer'}

        # 5) ferramentas simples
        tool = choose_tool(text)
        if tool == 'web':
            q = re.sub(r'(?i)pesquise|procure na internet|pesquisa na web', '', text, count=1).strip()
            return self._chat(user, text, f'Resultado da pesquisa na web:\n{web_search(q)}', 'web')
        if tool:
            t, result = execute_tool(text, tool)
            return {'reply': result, 'tool': t}

        # 6) conversa
        return self._chat(user, text, '', None)

    def _team(self, goal):
        out = self.team_run(goal)
        return {'reply': out['reply'], 'tool': 'equipe', 'trace': out['trace']}

    def _chat(self, user, text, tool_result, tool):
        if not self.llm:
            return {'reply': 'OPENROUTER_API_KEY não configurada neste serviço.', 'tool': tool}
        msgs = [{'role': 'system', 'content': self.system_prompt(tool_result)}] + self._history(user)[-10:] + [{'role': 'user', 'content': text}]
        return {'reply': (self.llm(msgs, temperature=0.4) or '').strip() or '...', 'tool': tool}
