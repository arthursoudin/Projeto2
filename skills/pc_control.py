"""Jarvis V11.9 - interpretador de comandos do PC.

Transforma frases do usuário em passos (acao, params) para o agente local.
Não depende de Streamlit, então pode ser testado sozinho.
"""
import re
import unicodedata

# ---------------------------------------------------------------- permissões
# livre     = executa direto
# confirmar = o Jarvis pergunta "sim/não" antes de executar
PERMISSIONS = {
    'system_info': 'livre', 'list_files': 'livre', 'read_file': 'livre', 'read_log': 'livre',
    'open_app': 'livre', 'open_url': 'livre', 'search_web': 'livre',
    'open_folder': 'livre', 'open_file': 'livre',
    'create_folder': 'livre', 'create_file': 'confirmar', 'append_file': 'confirmar',
    'copy_path': 'livre', 'move_path': 'livre', 'rename_path': 'livre',
    'delete_path': 'confirmar',
}
CONFIRM_ACTIONS = {a for a, lvl in PERMISSIONS.items() if lvl == 'confirmar'}

SITES = {
    'youtube': 'https://www.youtube.com', 'google': 'https://www.google.com',
    'gmail': 'https://mail.google.com', 'github': 'https://github.com',
    'whatsapp': 'https://web.whatsapp.com', 'instagram': 'https://www.instagram.com',
    'linkedin': 'https://www.linkedin.com', 'netflix': 'https://www.netflix.com',
    'spotify': 'https://open.spotify.com', 'drive': 'https://drive.google.com',
    'maps': 'https://maps.google.com', 'render': 'https://dashboard.render.com',
}
APPS = {
    'vscode': ['vs code', 'vscode', 'visual studio code'],
    'notepad': ['bloco de notas', 'notepad'],
    'calculator': ['calculadora', 'calculator'],
    'browser': ['navegador', 'chrome', 'google chrome', 'edge'],
    'paint': ['paint'],
    'explorer': ['explorador de arquivos', 'explorer'],
    'word': ['word'], 'excel': ['excel'], 'powerpoint': ['powerpoint'],
    'taskmgr': ['gerenciador de tarefas'],
}

_Q = r'["“\'‘`]'
_QC = r'["”\'’`]'
_DESK = r'(?:[áa]rea\s+de\s+trabalho|desktop|documentos|downloads|(?:meu\s+)?(?:pc|computador))'
_APP_TAIL = re.compile(r'\s+(?:no|com\s+o|com)\s+(vs\s*code|visual studio code|bloco de notas|notepad)\s*[.!?]*$', re.I)

_SPLIT = re.compile(
    r'\s*;\s*|,?\s+e\s+depois\s+|,?\s+depois\s+|,?\s+em\s+seguida\s+'
    r'|,?\s+e\s+ent[aã]o\s+|,?\s+ent[aã]o\s+|,?\s+e\s+tamb[eé]m\s+', re.I)
_INSIDE = re.compile(
    r'\s+e\s+(?:dentro\s+d(?:ela|essa\s+pasta)|nela)\s+(?:(?:crie|criar|cria)\s+)?(?:um\s+)?(?=arquivo|pasta)', re.I)


def _norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')


def _strip_q(s):
    s = (s or '').strip()
    m = re.match(rf'^{_Q}(.+?){_QC}', s, re.S)
    return m.group(1).strip() if m else s.strip(' \t.,;:!?')


def _after_noun(text, noun):
    m = re.search(rf'\b{noun}\b\s+(?:(?:chamad[ao]|com\s+(?:o\s+)?nome(?:\s+de)?|de\s+nome|nomead[ao])\s+)?(.+)$',
                  text, re.I | re.S)
    return m.group(1) if m else ''


def _app_from(text):
    n = _norm(text)
    if 'code' in n: return 'vscode'
    if 'bloco' in n or 'notepad' in n: return 'notepad'
    return None


def _split_loc(raw, ctx, inside=False):
    """Separa (nome, pasta) de frases como 'notas.txt na pasta Projetos' ou 'notas.txt dentro dela'."""
    raw = (raw or '').strip()
    quoted, rest = None, raw
    q = re.match(rf'^{_Q}(.+?){_QC}\s*(.*)$', raw, re.S)
    if q:
        quoted, rest = q.group(1).strip(), q.group(2)
    folder = ''
    # locais do Windows que o Jarvis não usa (tudo fica em ~/Jarvis): ignora
    rest = re.sub(rf'(?:^|\s+)(?:na|no|em|dentro\s+d[aeo]s?)\s+(?:minha\s+|meu\s+|a\s+|o\s+)?{_DESK}\b.*$', '', rest, flags=re.I)
    m = re.search(r'(?:^|\s+)(?:dentro\s+d(?:ela|essa|esta)(?:\s+pasta)?|nela)\s*[.!?]*$', rest, re.I)
    if m:
        folder = ctx.get('folder', ''); rest = rest[:m.start()]
    else:
        m = re.search(r'(?:^|\s+)(?:dentro\s+d[aeo]s?|d[aeo]|na|no|em)\s+(?:a\s+|o\s+)?pasta\s+(.+?)[\s.!?]*$', rest, re.I)
        if m:
            folder = _strip_q(m.group(1)); rest = rest[:m.start()]
    if folder.lower() == 'jarvis': folder = ''
    if inside and not folder: folder = ctx.get('folder', '')
    name = quoted if quoted is not None else rest.strip(' \t.,;:!?')
    return name, folder


def _join(folder, name):
    return f'{folder}/{name}' if folder and name else name


def _split_clauses(text):
    quotes = []

    def mask(m):
        quotes.append(m.group(0)); return f'\x00{len(quotes) - 1}\x00'

    masked = re.sub(r'"[^"]*"|“[^”]*”', mask, text)
    masked = _INSIDE.sub(' ; __in__ crie um ', masked)
    out = []
    for part in _SPLIT.split(masked):
        part = re.sub(r'\x00(\d+)\x00', lambda m: quotes[int(m.group(1))], part).strip()
        if part: out.append(part)
    return out


def _parse_clause(t, ctx):
    inside = t.startswith('__in__')
    if inside: t = t[6:].strip()
    n = _norm(t)

    # apagar (sempre pede confirmação)
    if re.search(r'\b(?:apague|apagar|apaga|exclua|excluir|delete|deletar|remova|remover)\s+(?:o\s+|a\s+)?(?:arquivo|pasta)\b', t, re.I):
        noun = 'arquivo' if re.search(r'\barquivo\b', t, re.I) else 'pasta'
        name, folder = _split_loc(_after_noun(t, noun), ctx)
        return ('delete_path', {'name': _join(folder, name)}) if name else None

    # renomear
    m = re.search(r'\b(?:renomeie|renomear|renomeia)\s+(?:o\s+|a\s+)?(?:arquivo\s+|pasta\s+)?(.+?)\s+para\s+(.+)$', t, re.I)
    if m:
        name, folder = _split_loc(m.group(1), ctx)
        new = _strip_q(m.group(2))
        return ('rename_path', {'name': _join(folder, name), 'new_name': new}) if name and new else None

    # mover / copiar
    m = re.search(r'\b(mova|mover|move|copie|copiar|copia)\s+(?:o\s+|a\s+)?(?:arquivo\s+|pasta\s+)?(.+?)\s+para\s+(?:a\s+|o\s+)?(pasta\s+)?(.+)$', t, re.I)
    if m:
        verb = _norm(m.group(1))
        src, sfolder = _split_loc(m.group(2), ctx)
        dst = _strip_q(m.group(4))
        if dst.lower() == 'jarvis': dst = '.'
        if not src or not dst: return None
        params = {'src': _join(sfolder, src), 'dst': dst}
        if m.group(3): params['into_folder'] = True
        return ('copy_path' if verb.startswith('copi') else 'move_path', params)

    # criar pasta
    if re.search(r'\b(?:crie|criar|cria|fa[cç]a|fazer|gere|gerar|monte)\s+(?:uma\s+|a\s+|essa\s+)?(?:nova\s+)?pasta\b', t, re.I):
        name, folder = _split_loc(_after_noun(t, 'pasta'), ctx, inside)
        if not name: return None
        path = _join(folder, name)
        ctx['folder'] = path; ctx['last'] = 'folder'
        return ('create_folder', {'name': path})

    # criar arquivo (aceita "com o texto ...")
    if re.search(r'\b(?:crie|criar|cria|fa[cç]a|fazer|gere|gerar)\s+(?:um\s+|o\s+)?(?:novo\s+)?arquivo\b', t, re.I):
        raw = _after_noun(t, 'arquivo'); content = ''
        parts = re.split(r'\s+com\s+(?:o\s+)?(?:texto|conte[úu]do)\s*:?\s*', raw, maxsplit=1, flags=re.I)
        raw = parts[0]
        if len(parts) > 1: content = _strip_q(parts[1])
        name, folder = _split_loc(raw, ctx, inside)
        if not name: return None
        path = _join(folder, name)
        ctx['file'] = path; ctx['last'] = 'file'
        return ('create_file', {'name': path, 'content': content})

    # escrever / acrescentar em arquivo existente
    m = re.search(rf'\b(?:escreva|escrever|adicione|adicionar|acrescente|acrescentar)\s+(?:no|ao|em)\s+(?:o\s+)?arquivo\s+'
                  rf'({_Q}[^"\'“”‘’`]+{_QC}|\S+)\s*(?::|\bo\s+texto\b|\bo\s+conte[úu]do\b|\bque\b)?\s*(.+)$', t, re.I | re.S)
    if m:
        name = _strip_q(m.group(1)); content = _strip_q(m.group(2))
        return ('append_file', {'name': name, 'content': content}) if name and content else None

    # ler arquivo
    if (re.search(r'\b(?:leia|ler|le)\s+(?:o\s+)?arquivo\b', n) or re.search(r'\bconteudo\s+d[oe]\s+(?:o\s+)?arquivo\b', n)
            or re.search(r'\bo que (?:tem|diz|esta escrito)\s+(?:no|em)\s+(?:o\s+)?arquivo\b', n)):
        name, folder = _split_loc(_after_noun(t, 'arquivo'), ctx)
        return ('read_file', {'name': _join(folder, name)}) if name else None

    # listar
    if re.search(r'\b(?:liste|listar|lista|mostre|mostrar|veja|ver|quais)\b.*\b(?:arquivos|pastas)\b', n) \
            or re.search(r'\bo que tem (?:na pasta|no jarvis)\b', n):
        m = re.search(r'\bpasta\s+(.+)$', t, re.I)
        name = _strip_q(m.group(1)) if m else ''
        if name.lower() in ('jarvis', ''): name = ''
        return ('list_files', {'name': name})

    # abrir "ela/ele" (referência ao que acabou de ser criado)
    m = re.search(r'^\W*(?:abra|abrir|abre)\s+(?P<w>ela|ele|essa\s+pasta|esse\s+arquivo|a\s+pasta|o\s+arquivo)(?P<tail>\s+(?:no|com\s+o|com)\s+.+?)?\W*$', t, re.I)
    if m:
        w = _norm(m.group('w')); app = _app_from(m.group('tail') or '')
        kind = 'folder' if ('ela' in w or 'pasta' in w) else 'file'
        if kind == 'folder' and ctx.get('folder'):
            return ('open_folder', {'name': ctx['folder'], **({'app': app} if app else {})})
        if kind == 'file' and ctx.get('file'):
            return ('open_file', {'name': ctx['file'], **({'app': app} if app else {})})
        if ctx.get('last') == 'file' and ctx.get('file'):
            return ('open_file', {'name': ctx['file'], **({'app': app} if app else {})})

    # abrir pasta / arquivo
    for noun, action in (('pasta', 'open_folder'), ('arquivo', 'open_file')):
        if re.search(rf'\b(?:abra|abrir|abre)\s+(?:(?:a|o|essa|esse)\s+)?{noun}\b', t, re.I):
            raw = _after_noun(t, noun); app = None
            tail = _APP_TAIL.search(raw)
            if tail: app = _app_from(tail.group(1)); raw = raw[:tail.start()]
            name, folder = _split_loc(raw, ctx)
            params = {'name': _join(folder, name)}
            if app: params['app'] = app
            if action == 'open_folder' or name: return (action, params)
            return None

    # informações do sistema / métricas do PC
    if (re.search(r'\b(?:informacoes?|info|dados|especificacoes?|configuracoes?|status)\b.{0,25}\b(?:pc|computador|sistema|maquina|notebook)\b', n)
            or re.search(r'\b(?:quanta|quanto|qual)\b.{0,30}\b(?:ram|disco|armazenamento|espaco|cpu|processador)\b', n)
            or re.search(r'\b(?:verifique|verificar|veja|mostrar|mostre|consulte|consultar)\b.{0,25}\b(?:cpu|processador|ram|memoria|disco|armazenamento)\b', n)
            or re.search(r'\b(?:uso|utilizacao|utilizacao|percentual|porcentagem)\b.{0,20}\b(?:cpu|processador|ram|memoria|disco)\b', n)):
        return ('system_info', {})

    # navegador: pesquisar
    for pat in (r'\b(?:pesquis[ae]r?|procur[ea]r?|busque|buscar)\s+(?:por\s+)?(.+?)\s+(?:no|na)\s+(google|youtube|navegador|chrome|internet)\b',
                r'\b(?:no|na)\s+(google|youtube|navegador|chrome)\s+(?:pesquis[ae]r?|procur[ea]r?|busque|buscar)\s+(?:por\s+)?(.+)$'):
        m = re.search(pat, t, re.I)
        if m:
            a, b = m.group(1), m.group(2)
            q, eng = (a, b) if pat.startswith(r'\b(?:pesquis') else (b, a)
            return ('search_web', {'query': _strip_q(q), 'engine': 'youtube' if _norm(eng) == 'youtube' else 'google'})

    # navegador: abrir site
    verbs = r'(?:abra|abrir|abre|acesse|acessar|entre\s+(?:no|em)|va\s+para)'
    m = re.search(rf'\b{verbs}\s+(?:o\s+|a\s+)?(?:site\s+(?:do\s+|da\s+|de\s+)?|p[aá]gina\s+(?:do\s+|da\s+|de\s+)?)?'
                  rf'((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|br|io|dev|app|gov|edu|ai|co)(?:/\S*)?)', t, re.I)
    if m: return ('open_url', {'url': m.group(1)})
    m = re.search(rf'\b{verbs}\s+(?:o\s+|a\s+)?(?:site\s+(?:do\s+|da\s+|de\s+)?)?({"|".join(SITES)})\b(?!\s+chrome)', n)
    if m: return ('open_url', {'url': SITES[m.group(1)]})

    # aplicativos
    if any(x in n for x in ['abra ', 'abrir ', 'abre ', 'inicie ', 'iniciar ']):
        for app, keys in APPS.items():
            if any(re.search(rf'\b{re.escape(k)}\b', n) for k in keys): return ('open_app', {'app': app})
    return None


def parse_pc_commands(text):
    """Frase -> lista de passos [(acao, params), ...]. Lista vazia = não é um comando de PC."""
    n = _norm(text or '')
    if re.search(r'\b(lembre|lembra|lembrete|tarefa)\b', n):  # "me lembre de apagar..." não é comando
        return []
    ctx, steps = {}, []
    for clause in _split_clauses(text or ''):
        step = _parse_clause(clause, ctx)
        if step: steps.append(step)
    return steps


def describe_step(action, params):
    p = params or {}
    if action == 'delete_path': return f"apagar \"{p.get('name')}\""
    if action in ('move_path', 'copy_path'): return f"{action.split('_')[0]} \"{p.get('src')}\" -> \"{p.get('dst')}\""
    return f"{action} {p.get('name') or p.get('app') or p.get('url') or p.get('query') or ''}".strip()


def is_confirm(text):
    return bool(re.fullmatch(r'(sim|s|confirmo|confirmar|pode|pode sim|pode apagar|claro|ok|isso|isso mesmo|apague|apaga)',
                             _norm(text).strip(' .!')))


def is_cancel(text):
    return bool(re.fullmatch(r'(nao|n|cancelar|cancela|cancele|deixa|deixa pra la|nao apague|melhor nao)',
                             _norm(text).strip(' .!')))
