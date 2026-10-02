"""Jarvis V12.6 - multiagentes.

Uma "equipe" de agentes especialistas coordenada por um Planejador:

  objetivo -> Planejador (LLM) -> etapas [{agente, instrucao}] -> cada agente executa -> relatório

Regras de segurança (de propósito):
  * O Planejador só escolhe entre os agentes registrados; nunca gera ações cruas.
  * O agente "pc" recebe uma FRASE em português e o interpretador determinístico (pc_control)
    decide a ação, com as mesmas permissões de sempre.
  * Equipes NUNCA apagam nada (apagar exige confirmação na hora, direto com o Jarvis).
  * O relatório final é montado a partir dos resultados reais das etapas, sem LLM,
    então o Jarvis não "inventa" que algo foi feito.

Não depende de Streamlit nem de FastAPI.
"""
import json
import re

MAX_STEPS = 6
MAX_INSTRUCTION = 400

AGENTS = {
    'pc': {
        'icone': '🖥️', 'nome': 'Agente do PC',
        'descricao': 'Cria pastas/arquivos, abre apps e sites, lista arquivos, agenda rotinas no PC. '
                     'A instrução é uma frase de comando, ex.: "crie a pasta Estudos e dentro dela o arquivo plano.txt".',
    },
    'tarefas': {
        'icone': '✅', 'nome': 'Agente de Tarefas',
        'descricao': 'Cria uma tarefa com prazo opcional. A instrução é o texto da tarefa, ex.: "estudar python amanhã às 9h".',
    },
    'memoria': {
        'icone': '🧠', 'nome': 'Agente de Memória',
        'descricao': 'Guarda um fato sobre o usuário. A instrução é o fato, ex.: "prefere estudar de manhã".',
    },
    'pesquisa': {
        'icone': '🔎', 'nome': 'Agente de Pesquisa',
        'descricao': 'Pesquisa na web e resume. A instrução é o tema/pergunta.',
    },
    'redator': {
        'icone': '✍️', 'nome': 'Agente Redator',
        'descricao': 'Escreve ou organiza texto (planos, resumos, listas, respostas). Recebe o resultado das etapas anteriores.',
    },
}

PLANNER_SYSTEM = (
    'Você é o Planejador da equipe Jarvis. Divida o objetivo do usuário em no máximo %d etapas, '
    'cada etapa para UM agente. Agentes disponíveis:\n%s\n\n'
    'Regras:\n'
    '- Use só os nomes de agentes acima.\n'
    '- Nunca crie etapas que apaguem, excluam ou removam arquivos/pastas.\n'
    '- Cada instrução deve ser curta, autossuficiente e em português.\n'
    '- Se o objetivo for só uma conversa ou pedido de texto, use UMA etapa com o agente "redator".\n'
    '- Se uma etapa usar o resultado de outra (ex.: escrever um plano e depois salvá-lo), ponha a de texto antes.\n'
    'Responda SOMENTE com JSON, sem comentários nem crases: '
    '{"etapas":[{"agente":"nome","instrucao":"texto"}]}'
)


def agents_listing():
    return '\n'.join(f'- {k}: {v["descricao"]}' for k, v in AGENTS.items())


def planner_prompt():
    return PLANNER_SYSTEM % (MAX_STEPS, agents_listing())


def parse_plan(text):
    """Texto do LLM -> lista validada de {'agente','instrucao'}, ou None se não der para aproveitar."""
    s = str(text or '')
    a, b = s.find('{'), s.rfind('}')
    if a < 0 or b <= a:
        return None
    try:
        data = json.loads(s[a:b + 1])
    except Exception:
        return None
    raw = data.get('etapas') if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    plan = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ag = str(item.get('agente', '')).strip().lower()
        ins = str(item.get('instrucao', '')).strip()
        if ag not in AGENTS or not ins:
            continue
        plan.append({'agente': ag, 'instrucao': ins[:MAX_INSTRUCTION]})
        if len(plan) >= MAX_STEPS:
            break
    return plan or None


def wants_team(text):
    """Quando acionar a equipe: comando /equipe, 'multiagente' ou pedidos de planejamento."""
    n = re.sub(r'\s+', ' ', str(text or '').lower()).strip()
    if n.startswith('/equipe') or n.startswith('equipe '):
        return True
    if re.search(r'\bmulti-?agentes?\b|\bequipe de agentes\b|\bagentes\b.{0,20}\b(?:juntos|trabalh)', n):
        return True
    if len(n) >= 30 and re.search(r'\b(?:planeje|planejar|monte um plano|crie um plano|faca um plano|faça um plano|organize (?:meu|minha|meus|minhas))\b', n):
        return True
    return False


def strip_trigger(text):
    t = str(text or '').strip()
    return re.sub(r'^\s*(?:/equipe|equipe)\s*[:,-]?\s*', '', t, flags=re.I).strip() or t


class Team:
    """handlers: {nome_do_agente: fn(instrucao, ctx) -> (ok, texto)}; llm: fn(messages, temperature) -> str."""

    def __init__(self, llm, handlers):
        self.llm = llm
        self.handlers = handlers

    def plan(self, goal):
        if not self.llm:
            return None
        try:
            out = self.llm([{'role': 'system', 'content': planner_prompt()},
                            {'role': 'user', 'content': goal}], temperature=0.2)
        except Exception:
            return None
        return parse_plan(out)

    def run(self, goal):
        goal = str(goal or '').strip()
        plan = self.plan(goal)
        planned = plan is not None
        if not plan:                                   # sem plano utilizável: o Redator responde direto
            plan = [{'agente': 'redator', 'instrucao': goal}]
        trace, stopped = [], False
        for i, step in enumerate(plan, 1):
            ag, ins = step['agente'], step['instrucao']
            if stopped:
                trace.append({'n': i, 'agente': ag, 'instrucao': ins, 'ok': None, 'saida': 'não executada (uma etapa anterior falhou)'})
                continue
            fn = self.handlers.get(ag)
            if not fn:
                ok, out = False, f'Agente "{ag}" indisponível.'
            else:
                try:
                    ok, out = fn(ins, {'goal': goal, 'trace': list(trace)})
                except Exception as e:
                    ok, out = False, f'Erro inesperado: {type(e).__name__}: {e}'
            trace.append({'n': i, 'agente': ag, 'instrucao': ins, 'ok': bool(ok), 'saida': str(out)})
            if not ok:
                stopped = True
        return {'goal': goal, 'planned': planned, 'trace': trace, 'reply': self.report(trace, planned),
                'ok': all(t['ok'] for t in trace)}

    @staticmethod
    def report(trace, planned=True):
        n = len(trace)
        head = f'🤖 Equipe Jarvis — {n} etapa{"s" if n != 1 else ""}' + ('' if planned else ' (sem plano; resposta direta)')
        blocks = [head]
        for t in trace:
            ag = AGENTS.get(t['agente'], {})
            mark = '⏭️' if t['ok'] is None else '✅' if t['ok'] else '❌'
            if t['agente'] == 'redator' and t['ok']:
                blocks.append(f"{t['n']}. {ag.get('icone', '')} {ag.get('nome', t['agente'])} {mark}\n{t['saida']}")
            else:
                blocks.append(f"{t['n']}. {ag.get('icone', '')} {ag.get('nome', t['agente'])} {mark} {t['instrucao']}\n→ {t['saida']}")
        return '\n\n'.join(blocks)
