import os
import asyncio
import ast
import json
import re
import uuid
import socket
import ipaddress
from urllib.parse import quote_plus, urlparse
from bs4 import BeautifulSoup
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import streamlit as st
from openai import OpenAI
import edge_tts

try:
    from honcho import Honcho
except Exception:
    Honcho = None

# ============================================================
# JARVIS v6 — identidade + memória + multiagente + Skills + Tools + Web
# ============================================================

MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
API_KEY = os.environ.get("OPENROUTER_API_KEY")
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)

HONCHO_API_KEY = os.environ.get("HONCHO_API_KEY")
HONCHO_WORKSPACE_ID = os.environ.get("HONCHO_WORKSPACE_ID", "jarvis")

st.set_page_config(page_title="Jarvis Agent", page_icon="🤖", layout="wide")

DEFAULT_AGENTS = [
    {"id": "programador", "nome": "Programador", "especialidade": "Python, JavaScript, HTML, CSS, backend e arquitetura de software", "skills": ["programacao"], "tools": ["calculadora", "hora_atual", "texto", "web_search", "web_open"]},
    {"id": "banco", "nome": "Banco de Dados", "especialidade": "SQL, PostgreSQL, modelagem, relacionamentos e integridade", "skills": ["postgresql"], "tools": ["calculadora", "hora_atual", "texto", "web_search", "web_open"]},
    {"id": "qa", "nome": "QA / Testes", "especialidade": "testes, bugs, casos extremos, validação e qualidade", "skills": ["qa"], "tools": ["calculadora", "hora_atual", "texto", "web_search", "web_open"]},
]

DEFAULT_SKILLS = {
    "programacao": "Analise requisitos, proponha arquitetura simples, escreva soluções claras e considere erros, manutenção e testes. Não diga que executou código se não executou.",
    "postgresql": "Pense em tabelas, chaves, relacionamentos, constraints, tipos, consultas e desempenho. Use SQL válido e explique riscos de modelagem.",
    "qa": "Procure bugs, casos extremos, entradas inválidas, regressões e critérios de aceitação. Transforme problemas em testes verificáveis.",
    "web": "Considere HTML semântico, CSS responsivo, JavaScript no navegador, acessibilidade e separação entre frontend e backend.",
    "planejamento": "Quebre objetivos grandes em tarefas pequenas, independentes e verificáveis. Defina dependências, prioridade e critério de conclusão.",
}

# ---------------------------
# Tools: somente ferramentas determinísticas e locais nesta versão
# ---------------------------

def _safe_calculator(expression: str):
    """Calculadora segura para operações matemáticas básicas."""
    allowed = (ast.Expression, ast.Constant, ast.UnaryOp, ast.BinOp,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
               ast.USub, ast.UAdd, ast.FloorDiv, ast.Load)
    tree = ast.parse(expression.strip(), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError("A expressão contém uma operação não permitida.")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("Apenas números são permitidos.")
    value = eval(compile(tree, "<calculator>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(value, (int, float)):
        raise ValueError("Resultado inválido.")
    return value


def tool_calculadora(args):
    return {"resultado": _safe_calculator(str(args.get("expressao", "")))}


def tool_hora_atual(args):
    now = datetime.now().astimezone()
    return {"iso": now.isoformat(), "data_hora": now.strftime("%d/%m/%Y %H:%M:%S"), "fuso": str(now.tzinfo)}


def tool_texto(args):
    text = str(args.get("texto", ""))
    return {
        "caracteres": len(text),
        "palavras": len(re.findall(r"\S+", text)),
        "linhas": len(text.splitlines()) if text else 0,
        "vazio": not bool(text.strip()),
    }


# ---------------------------
# Web: pesquisa e leitura controladas
# ---------------------------
WEB_TIMEOUT = int(os.environ.get("WEB_TIMEOUT", "15"))
WEB_MAX_CHARS = int(os.environ.get("WEB_MAX_CHARS", "12000"))
USER_AGENT = os.environ.get("WEB_USER_AGENT", "JarvisAgent/6.0 (research assistant)")


def _is_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
                return False
    except Exception:
        # Se não conseguirmos resolver, a requisição será tratada como erro.
        return False
    return True


def _http_get(url):
    if not _is_public_url(url):
        raise ValueError("URL não permitida: apenas sites públicos HTTP/HTTPS podem ser acessados.")
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
    response = requests.get(url, headers=headers, timeout=WEB_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    if not _is_public_url(response.url):
        raise ValueError("O redirecionamento levou para um endereço não permitido.")
    return response


def tool_web_search(args):
    query = str(args.get("consulta", "")).strip()
    if not query:
        raise ValueError("Informe uma consulta de pesquisa.")
    max_results = max(1, min(int(args.get("max_resultados", 5)), 8))
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    response = _http_get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for item in soup.select(".result")[:max_results]:
        title_el = item.select_one(".result__a")
        snippet_el = item.select_one(".result__snippet")
        if not title_el:
            continue
        href = title_el.get("href", "")
        title = title_el.get_text(" ", strip=True)
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        if href:
            results.append({"titulo": title, "url": href, "resumo": snippet})
    return {"consulta": query, "resultados": results, "quantidade": len(results)}


def tool_web_open(args):
    url = str(args.get("url", "")).strip()
    if not url:
        raise ValueError("Informe uma URL.")
    response = _http_get(url)
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return {"url": response.url, "tipo": content_type, "conteudo": "O recurso não é uma página HTML legível."}
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body
    text = main.get_text(" ", strip=True) if main else soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return {"url": response.url, "titulo": title, "conteudo": text[:WEB_MAX_CHARS], "truncado": len(text) > WEB_MAX_CHARS}


TOOLS = {
    "calculadora": {
        "descricao": "Calcula expressões matemáticas básicas com segurança.",
        "schema": '{"expressao":"2 * (10 + 5)"}',
        "run": tool_calculadora,
    },
    "hora_atual": {
        "descricao": "Obtém data, hora e fuso horário atuais do servidor.",
        "schema": '{}',
        "run": tool_hora_atual,
    },
    "texto": {
        "descricao": "Conta caracteres, palavras e linhas de um texto.",
        "schema": '{"texto":"texto para analisar"}',
        "run": tool_texto,
    },
    "web_search": {
        "descricao": "Pesquisa a web e retorna resultados públicos com título, URL e resumo.",
        "schema": '{"consulta":"pesquisa sobre o tema","max_resultados":5}',
        "run": tool_web_search,
    },
    "web_open": {
        "descricao": "Abre uma página pública HTTP/HTTPS e extrai o texto principal para análise.",
        "schema": '{"url":"https://exemplo.com"}',
        "run": tool_web_open,
    },
}

# ---------------------------
# Estado
# ---------------------------
if "messages" not in st.session_state: st.session_state.messages = []
if "agents" not in st.session_state: st.session_state.agents = [dict(a) for a in DEFAULT_AGENTS]
if "skills" not in st.session_state: st.session_state.skills = dict(DEFAULT_SKILLS)
if "mission_history" not in st.session_state: st.session_state.mission_history = []
if "memory" not in st.session_state: st.session_state.memory = []
if "settings" not in st.session_state:
    st.session_state.settings = {"max_workers": 6, "auto_review": True, "allow_tools": True, "require_tool_confirmation": True}
if "identity" not in st.session_state:
    st.session_state.identity = {
        "nome": os.environ.get("JARVIS_NAME", "Jarvis"),
        "papel": os.environ.get("JARVIS_ROLE", "assistente pessoal e orquestrador multiagente"),
        "criador": os.environ.get("JARVIS_CREATOR", "Usuário"),
        "empresa": os.environ.get("JARVIS_COMPANY", ""),
        "objetivo": os.environ.get("JARVIS_OBJECTIVE", "Ajudar o usuário a planejar, resolver problemas e coordenar agentes com honestidade."),
        "personalidade": os.environ.get("JARVIS_PERSONALITY", "inteligente, direto, educado, técnico quando necessário e levemente sarcástico"),
        "regras": os.environ.get("JARVIS_RULES", "Não inventar ações executadas, não esconder erros e pedir confirmação antes de ações externas."),
    }
if "honcho_session_id" not in st.session_state: st.session_state.honcho_session_id = f"chat-{uuid.uuid4().hex[:12]}"
if "honcho_status" not in st.session_state: st.session_state.honcho_status = "não configurado"


def identity_text():
    i = st.session_state.identity
    return f"""IDENTIDADE DO JARVIS\nNome: {i['nome']}\nPapel: {i['papel']}\nCriador/usuário principal: {i['criador']}\nEmpresa/projeto: {i['empresa'] or 'não informado'}\nObjetivo: {i['objetivo']}\nPersonalidade: {i['personalidade']}\nRegras: {i['regras']}"""


def get_honcho():
    if Honcho is None or not HONCHO_API_KEY:
        st.session_state.honcho_status = "não configurado"
        return None, None, None, None
    try:
        h = Honcho(workspace_id=HONCHO_WORKSPACE_ID, api_key=HONCHO_API_KEY)
        user_peer = h.peer("usuario")
        jarvis_peer = h.peer("jarvis")
        session = h.session(st.session_state.honcho_session_id)
        st.session_state.honcho_status = "conectado"
        return h, user_peer, jarvis_peer, session
    except Exception as exc:
        st.session_state.honcho_status = f"erro: {exc}"
        return None, None, None, None


def recall_memory(query):
    if not HONCHO_API_KEY or Honcho is None:
        return "Memória persistente não configurada."
    try:
        _, user_peer, _, _ = get_honcho()
        if user_peer is None: return "Memória persistente indisponível."
        return str(user_peer.chat(query))
    except Exception as exc:
        return f"Não foi possível consultar a memória persistente: {exc}"


def save_exchange(user_text, assistant_text):
    if not HONCHO_API_KEY or Honcho is None: return
    try:
        _, user_peer, jarvis_peer, session = get_honcho()
        if session is not None:
            session.add_messages([user_peer.message(user_text), jarvis_peer.message(assistant_text)])
    except Exception as exc:
        st.session_state.honcho_status = f"erro ao salvar: {exc}"


def ask(system_prompt, user_prompt, temperature=0.3):
    if not API_KEY: raise RuntimeError("OPENROUTER_API_KEY não está configurada no Render.")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content or "Sem resposta."


def clean_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match: return None
    try: return json.loads(match.group(0))
    except Exception: return None


def skill_text(names):
    return "\n\n".join(st.session_state.skills[n] for n in names or [] if n in st.session_state.skills) or "Nenhuma skill específica foi carregada."


def memory_text():
    return "\n".join(f"- {m}" for m in st.session_state.memory[-20:]) or "Nenhuma memória relevante registrada nesta sessão."


def tool_catalog(names=None):
    names = names or list(TOOLS)
    return "\n".join(f"- {n}: {TOOLS[n]['descricao']} | argumentos exemplo: {TOOLS[n]['schema']}" for n in names if n in TOOLS) or "Nenhuma ferramenta permitida."


def plan_mission(objective, agents):
    team = "\n".join(f'- {a["id"]}: {a["nome"]} | {a["especialidade"]} | skills={a.get("skills", [])} | tools={a.get("tools", [])}' for a in agents)
    raw = ask(
        """Você é o CHEFE/ORQUESTRADOR. Não execute o trabalho.\nDecomponha a missão em tarefas independentes. Para cada tarefa, informe ferramentas que podem ser úteis.\nResponda SOMENTE JSON válido:\n{\"tarefas\":[{\"agente\":\"id\",\"tarefa\":\"descrição\",\"prioridade\":\"alta|media|baixa\",\"tools\":[\"nome_da_tool\"]}]}\nUse apenas IDs e ferramentas fornecidos. Não invente agentes ou ferramentas.""",
        f"{identity_text()}\n\nMEMÓRIA PERSISTENTE:\n{recall_memory(objective)}\n\nMISSÃO:\n{objective}\n\nEQUIPE:\n{team}\n\nFERRAMENTAS DISPONÍVEIS:\n{tool_catalog()}\n\nMEMÓRIA DA SESSÃO:\n{memory_text()}", 0.15)
    data = clean_json(raw)
    if data and isinstance(data.get("tarefas"), list): return data["tarefas"], raw
    return [{"agente": a["id"], "tarefa": f"Analise a missão pela especialidade {a['especialidade']} e entregue uma proposta concreta.", "prioridade": "media", "tools": []} for a in agents], raw


def decide_tool_calls(agent, objective, task, allowed_tools):
    if not st.session_state.settings["allow_tools"] or not allowed_tools:
        return []
    catalog = tool_catalog(allowed_tools)
    raw = ask(
        """Você é um seletor de ferramentas. Só pode escolher ferramentas do catálogo.\nResponda SOMENTE JSON válido: {\"calls\":[{\"tool\":\"nome\",\"args\":{...},\"motivo\":\"...\"}]}\nSe nenhuma ferramenta for necessária, use {\"calls\":[]}. Não invente ferramentas.""",
        f"MISSÃO: {objective}\nTAREFA: {task}\nAGENTE: {agent['nome']}\nCATÁLOGO:\n{catalog}", 0.0)
    data = clean_json(raw)
    if not data or not isinstance(data.get("calls"), list): return []
    safe = []
    for call in data["calls"]:
        if call.get("tool") in allowed_tools and call["tool"] in TOOLS and isinstance(call.get("args", {}), dict):
            safe.append(call)
    return safe[:5]


def execute_tools(calls):
    outputs = []
    for call in calls:
        name = call["tool"]
        try:
            result = TOOLS[name]["run"](call.get("args", {}))
            outputs.append({"tool": name, "args": call.get("args", {}), "ok": True, "result": result, "motivo": call.get("motivo", "")})
        except Exception as exc:
            outputs.append({"tool": name, "args": call.get("args", {}), "ok": False, "error": str(exc), "motivo": call.get("motivo", "")})
    return outputs


def run_worker(agent, objective, task, all_plan, planned_tools):
    allowed = [x for x in planned_tools if x in agent.get("tools", []) and x in TOOLS]
    calls = decide_tool_calls(agent, objective, task, allowed)
    tool_outputs = execute_tools(calls) if calls else []
    system = f"""{identity_text()}\n\nVocê é o agente {agent['nome']}.\nEspecialidade: {agent['especialidade']}\n\nSKILLS:\n{skill_text(agent.get('skills', []))}\n\nREGRAS DE FERRAMENTAS:\nVocê só pode considerar como fatos os resultados realmente retornados pelas ferramentas. Não invente execução."""
    prompt = f"""MISSÃO:\n{objective}\n\nSUA TAREFA:\n{task}\n\nPLANO:\n{all_plan}\n\nRESULTADOS REAIS DAS FERRAMENTAS:\n{json.dumps(tool_outputs, ensure_ascii=False, indent=2)}\n\nMEMÓRIA:\n{memory_text()}\n\nEntregue análise, solução/proposta, riscos e resultado útil para o Revisor."""
    answer = ask(system, prompt, 0.3)
    return {"resposta": answer, "tool_calls": tool_outputs}


def review(objective, tasks, results):
    deliveries = "\n\n".join(f"### {name}\n{json.dumps(text, ensure_ascii=False, indent=2)}" for name, text in results.items())
    return ask("Você é o REVISOR. Verifique o trabalho contra a missão. Procure contradições, lacunas, erros técnicos e requisitos esquecidos. Não invente fatos.", f"{identity_text()}\n\nMISSÃO:\n{objective}\n\nTAREFAS:\n{json.dumps(tasks, ensure_ascii=False, indent=2)}\n\nENTREGAS:\n{deliveries}\n\nRetorne: 1. Acertos 2. Problemas 3. Correções 4. Critério de conclusão", 0.2)


def synthesize(objective, tasks, results, revision):
    deliveries = "\n\n".join(f"### {name}\n{json.dumps(text, ensure_ascii=False, indent=2)}" for name, text in results.items())
    return ask("Você é o CHEFE FINAL. Consolide o trabalho em português. Diferencie claramente análise/proposta de ações realmente executadas. Não diga que executou algo que não ocorreu.", f"{identity_text()}\n\nMISSÃO:\n{objective}\n\nTAREFAS:\n{json.dumps(tasks, ensure_ascii=False, indent=2)}\n\nAGENTES:\n{deliveries}\n\nREVISÃO:\n{revision}\n\nProduza uma resposta prática com conclusão e próximos passos.", 0.25)


def execute_engine(objective, agents):
    started = datetime.now()
    tasks, plan_raw = plan_mission(objective, agents)
    by_id = {t.get("agente"): t for t in tasks if isinstance(t, dict)}
    results = {}
    selected = [a for a in agents if a["id"] in by_id]
    max_workers = min(max(1, st.session_state.settings["max_workers"]), max(1, len(selected)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_worker, a, objective, by_id[a["id"]].get("tarefa", ""), plan_raw, by_id[a["id"]].get("tools", [])): a["nome"] for a in selected}
        for future in as_completed(futures):
            name = futures[future]
            try: results[name] = future.result()
            except Exception as exc: results[name] = {"resposta": f"ERRO: {exc}", "tool_calls": []}
    revision = review(objective, tasks, results) if st.session_state.settings["auto_review"] else "Revisão desativada."
    final = synthesize(objective, tasks, results, revision)
    finished = datetime.now()
    report = {"inicio": started.strftime("%d/%m/%Y %H:%M:%S"), "fim": finished.strftime("%d/%m/%Y %H:%M:%S"), "modelo": MODEL, "missao": objective, "tarefas": tasks, "resultados": results, "revisao": revision, "final": final}
    st.session_state.mission_history.insert(0, report)
    return report


async def make_audio(text, filename):
    await edge_tts.Communicate(text, "pt-BR-AntonioNeural").save(filename)

# ============================================================
# UI
# ============================================================
st.title("🤖 Jarvis Agent V6")
st.caption(f"Multiagente • Skills • Tools • Web • Memória • {MODEL}")

with st.sidebar:
    st.header("⚙️ Configuração")
    st.session_state.settings["max_workers"] = st.slider("Agentes em paralelo", 1, 10, st.session_state.settings["max_workers"])
    st.session_state.settings["auto_review"] = st.checkbox("Revisor automático", value=st.session_state.settings["auto_review"])
    st.session_state.settings["allow_tools"] = st.checkbox("Permitir ferramentas", value=st.session_state.settings["allow_tools"])
    st.session_state.settings["require_tool_confirmation"] = st.checkbox("Exigir confirmação para ferramentas externas", value=st.session_state.settings["require_tool_confirmation"])

    st.divider(); st.header("🪪 Identidade")
    i = st.session_state.identity
    i["nome"] = st.text_input("Nome", value=i["nome"], key="identity_nome")
    i["papel"] = st.text_input("Papel", value=i["papel"], key="identity_papel")
    i["criador"] = st.text_input("Criador / usuário", value=i["criador"], key="identity_criador")
    i["empresa"] = st.text_input("Empresa / projeto", value=i["empresa"], key="identity_empresa")
    i["objetivo"] = st.text_area("Objetivo", value=i["objetivo"], key="identity_objetivo", height=70)
    i["personalidade"] = st.text_area("Personalidade", value=i["personalidade"], key="identity_personalidade", height=70)
    i["regras"] = st.text_area("Regras", value=i["regras"], key="identity_regras", height=70)

    st.divider(); st.header("🧠 Memória")
    if HONCHO_API_KEY:
        st.success(f"Honcho: {st.session_state.honcho_status}")
        memory_question = st.text_input("Consultar memória", key="memory_question")
        if st.button("Consultar Honcho") and memory_question: st.info(recall_memory(memory_question))
    else: st.warning("Honcho não configurado.")

    st.divider(); st.header("🌐 Web")
    st.caption("O Jarvis pode pesquisar e ler páginas públicas. A camada bloqueia localhost e endereços privados.")

    st.divider(); st.header("🛠️ Tools disponíveis")
    for name, tool in TOOLS.items():
        st.write(f"**{name}** — {tool['descricao']}")

    st.divider(); st.header("👥 Equipe")
    for idx, agent in enumerate(st.session_state.agents):
        with st.expander(agent["nome"]):
            st.write(agent["especialidade"])
            st.caption("Skills: " + ", ".join(agent.get("skills", [])))
            st.caption("Tools: " + ", ".join(agent.get("tools", [])))
            if st.button("Remover", key=f"remove_agent_{idx}"):
                st.session_state.agents.pop(idx); st.rerun()

    with st.expander("➕ Novo agente"):
        new_name = st.text_input("Nome", key="new_agent_name")
        new_spec = st.text_input("Especialidade", key="new_agent_spec")
        new_skills = st.multiselect("Skills", list(st.session_state.skills), key="new_agent_skills")
        new_tools = st.multiselect("Tools", list(TOOLS), key="new_agent_tools")
        if st.button("Adicionar agente") and new_name and new_spec:
            slug = re.sub(r"[^a-z0-9]+", "_", new_name.lower()).strip("_") or f"agente_{len(st.session_state.agents)+1}"
            st.session_state.agents.append({"id": slug, "nome": new_name, "especialidade": new_spec, "skills": new_skills, "tools": new_tools}); st.rerun()

    st.divider(); st.header("🧩 Skills")
    for name in st.session_state.skills: st.write("• " + name)
    with st.expander("➕ Criar skill"):
        skill_name = st.text_input("Nome", key="skill_name")
        skill_content = st.text_area("Instruções", key="skill_content", height=100)
        if st.button("Salvar skill") and skill_name and skill_content:
            slug = re.sub(r"[^a-z0-9]+", "_", skill_name.lower()).strip("_")
            st.session_state.skills[slug] = skill_content; st.rerun()

    st.divider(); st.header("🧠 Memória da sessão")
    memory_item = st.text_input("Adicionar memória", key="memory_item")
    if st.button("Guardar memória") and memory_item:
        st.session_state.memory.append(memory_item); st.rerun()

chat_tab, team_tab, history_tab, tools_tab, web_tab = st.tabs(["💬 Chat", "🧩 Motor", "📜 Histórico", "🛠️ Tools", "🌐 Web"])

with chat_tab:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]): st.markdown(message["content"])
    if prompt := st.chat_input("Fale com o Jarvis..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Chefe planejando, agentes trabalhando e ferramentas sendo avaliadas..."):
                try:
                    report = execute_engine(prompt, st.session_state.agents)
                    answer = report["final"]
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    save_exchange(prompt, answer)
                    audio_file = "/tmp/jarvis_resposta.mp3"
                    try:
                        asyncio.run(make_audio(answer, audio_file)); st.audio(audio_file, format="audio/mp3", autoplay=True)
                    except Exception as audio_error: st.caption(f"Áudio indisponível: {audio_error}")
                except Exception as exc: st.error(f"Erro no motor: {exc}")

with team_tab:
    st.subheader("🧩 Motor multiagente")
    cols = st.columns(5)
    cols[0].metric("Agentes", len(st.session_state.agents)); cols[1].metric("Skills", len(st.session_state.skills)); cols[2].metric("Tools", len(TOOLS)); cols[3].metric("Memórias", len(st.session_state.memory)); cols[4].metric("Missões", len(st.session_state.mission_history))
    st.divider(); st.markdown("### Equipe ativa")
    for agent in st.session_state.agents:
        st.markdown(f"**{agent['nome']}** — {agent['especialidade']}")
        st.caption("Skills: " + (", ".join(agent.get("skills", [])) or "nenhuma") + " | Tools: " + (", ".join(agent.get("tools", [])) or "nenhuma"))
    if st.session_state.mission_history:
        last = st.session_state.mission_history[0]
        st.divider(); st.info(last["missao"]); st.markdown("### Plano"); st.json(last["tarefas"])

with history_tab:
    st.subheader("📜 Histórico")
    for idx, item in enumerate(st.session_state.mission_history):
        with st.expander(f"#{idx+1} • {item['inicio']} • {item['missao'][:80]}"):
            st.markdown("### Resultado final"); st.markdown(item["final"])
            st.markdown("### Ferramentas usadas")
            for name, result in item["resultados"].items():
                st.markdown(f"**{name}**")
                st.json(result.get("tool_calls", []))
            st.markdown("### Revisão"); st.markdown(item["revisao"])

with tools_tab:
    st.subheader("🛠️ Central de ferramentas")
    st.write("Nesta V5 as ferramentas são executadas por uma camada controlada. O agente não recebe acesso arbitrário ao servidor.")
    for name, tool in TOOLS.items():
        with st.expander(name):
            st.write(tool["descricao"]); st.code(tool["schema"], language="json")
            st.caption("Executada apenas quando o agente a seleciona e o agente possui permissão para ela.")


with web_tab:
    st.subheader("🌐 Pesquisa Web")
    st.write("Teste manualmente as ferramentas de pesquisa e leitura. O mesmo mecanismo pode ser usado pelos agentes durante uma missão.")
    web_query = st.text_input("Pesquisar na web", key="web_query")
    web_n = st.slider("Resultados", 1, 8, 5, key="web_n")
    if st.button("Pesquisar", key="web_search_button") and web_query:
        try:
            data = tool_web_search({"consulta": web_query, "max_resultados": web_n})
            st.session_state["last_web_results"] = data.get("resultados", [])
            for i, item in enumerate(data.get("resultados", []), 1):
                st.markdown(f"### {i}. {item['titulo']}")
                st.write(item.get("resumo", ""))
                st.code(item["url"], language="text")
        except Exception as exc:
            st.error(f"Erro na pesquisa: {exc}")

    st.divider()
    web_url = st.text_input("Abrir URL pública", key="web_url")
    if st.button("Ler página", key="web_open_button") and web_url:
        try:
            page = tool_web_open({"url": web_url})
            st.markdown(f"### {page.get('titulo', 'Página')}")
            st.caption(page.get("url", web_url))
            st.text_area("Conteúdo extraído", page.get("conteudo", ""), height=350)
        except Exception as exc:
            st.error(f"Erro ao abrir página: {exc}")
