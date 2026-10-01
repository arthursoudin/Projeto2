import os
import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import streamlit as st
from openai import OpenAI
import edge_tts

# ============================================================
# JARVIS v3 — motor multiagente com Skills
# ============================================================

MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
API_KEY = os.environ.get("OPENROUTER_API_KEY")
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)

st.set_page_config(page_title="Jarvis Agent", page_icon="🤖", layout="wide")

DEFAULT_AGENTS = [
    {"id": "programador", "nome": "Programador", "especialidade": "Python, JavaScript, HTML, CSS, backend e arquitetura de software", "skills": ["programacao"]},
    {"id": "banco", "nome": "Banco de Dados", "especialidade": "SQL, PostgreSQL, modelagem, relacionamentos e integridade", "skills": ["postgresql"]},
    {"id": "qa", "nome": "QA / Testes", "especialidade": "testes, bugs, casos extremos, validação e qualidade", "skills": ["qa"]},
]

DEFAULT_SKILLS = {
    "programacao": """# Skill: Programação\nAnalise requisitos, proponha arquitetura simples, escreva soluções claras e considere erros, manutenção e testes. Não diga que executou código se não executou.""",
    "postgresql": """# Skill: PostgreSQL\nPense em tabelas, chaves, relacionamentos, constraints, tipos, consultas e desempenho. Use SQL válido e explique riscos de modelagem.""",
    "qa": """# Skill: QA\nProcure bugs, casos extremos, entradas inválidas, regressões e critérios de aceitação. Transforme problemas em testes verificáveis.""",
    "web": """# Skill: Web\nConsidere HTML semântico, CSS responsivo, JavaScript no navegador, acessibilidade e separação entre frontend e backend.""",
    "planejamento": """# Skill: Planejamento\nQuebre objetivos grandes em tarefas pequenas, independentes e verificáveis. Defina dependências, prioridade e critério de conclusão.""",
}

# ---------------------------
# Estado
# ---------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agents" not in st.session_state:
    st.session_state.agents = [dict(a) for a in DEFAULT_AGENTS]
if "skills" not in st.session_state:
    st.session_state.skills = dict(DEFAULT_SKILLS)
if "mission_history" not in st.session_state:
    st.session_state.mission_history = []
if "memory" not in st.session_state:
    st.session_state.memory = []
if "settings" not in st.session_state:
    st.session_state.settings = {"max_workers": 6, "max_steps": 1, "auto_review": True}


def ask(system_prompt, user_prompt, temperature=0.3):
    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY não está configurada no Render.")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content or "Sem resposta."


def clean_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def skill_text(names):
    parts = []
    for name in names or []:
        if name in st.session_state.skills:
            parts.append(st.session_state.skills[name])
    return "\n\n".join(parts) or "Nenhuma skill específica foi carregada."


def memory_text():
    if not st.session_state.memory:
        return "Nenhuma memória relevante registrada nesta sessão."
    return "\n".join(f"- {m}" for m in st.session_state.memory[-20:])


def plan_mission(objective, agents):
    team = "\n".join(
        f'- {a["id"]}: {a["nome"]} | {a["especialidade"]} | skills={a.get("skills", [])}'
        for a in agents
    )
    raw = ask(
        """Você é o CHEFE/ORQUESTRADOR. Não execute o trabalho.\n\nSua função é decompor a missão em tarefas independentes para especialistas.\nResponda SOMENTE com JSON válido:\n{\"tarefas\":[{\"agente\":\"id\",\"tarefa\":\"descrição\",\"prioridade\":\"alta|media|baixa\"}]}\nUse apenas IDs da equipe. Não invente agentes.""",
        f"MISSÃO:\n{objective}\n\nEQUIPE:\n{team}\n\nMEMÓRIA:\n{memory_text()}\n\nCrie tarefas objetivas e verificáveis.",
        0.15,
    )
    data = clean_json(raw)
    if data and isinstance(data.get("tarefas"), list):
        return data["tarefas"], raw
    # fallback: não deixa a missão morrer se o modelo quebrar o JSON
    return [
        {"agente": a["id"], "tarefa": f"Analise a missão pela especialidade {a['especialidade']} e entregue uma proposta concreta.", "prioridade": "media"}
        for a in agents
    ], raw


def run_worker(agent, objective, task, all_plan):
    skills = skill_text(agent.get("skills", []))
    system = f"""Você é o agente {agent['nome']}.\nEspecialidade: {agent['especialidade']}\n\nSKILLS CARREGADAS:\n{skills}\n\nVocê trabalha dentro de uma equipe. Seja técnico, concreto e honesto. Não alegue ter executado ferramentas ou alterado arquivos quando isso não aconteceu."""
    prompt = f"""MISSÃO:\n{objective}\n\nSUA TAREFA:\n{task}\n\nPLANO:\n{all_plan}\n\nMEMÓRIA:\n{memory_text()}\n\nEntregue:\n- análise\n- solução/proposta\n- riscos\n- resultado útil para o Revisor"""
    return ask(system, prompt, 0.3)


def review(objective, tasks, results):
    deliveries = "\n\n".join(f"### {name}\n{text}" for name, text in results.items())
    return ask(
        """Você é o REVISOR. Verifique o trabalho dos agentes contra a missão.\nProcure contradições, lacunas, erros técnicos e requisitos esquecidos.\nNão invente fatos. Seja objetivo.""",
        f"MISSÃO:\n{objective}\n\nTAREFAS:\n{json.dumps(tasks, ensure_ascii=False, indent=2)}\n\nENTREGAS:\n{deliveries}\n\nRetorne:\n1. Acertos\n2. Problemas\n3. Correções necessárias\n4. Critério para considerar concluído",
        0.2,
    )


def synthesize(objective, tasks, results, revision):
    deliveries = "\n\n".join(f"### {name}\n{text}" for name, text in results.items())
    return ask(
        """Você é o CHEFE FINAL. Consolide o trabalho em português.\nDiferencie claramente análise/proposta de ações realmente executadas.\nNão diga que alterou arquivos, enviou mensagens ou executou comandos se isso não ocorreu.""",
        f"MISSÃO:\n{objective}\n\nTAREFAS:\n{json.dumps(tasks, ensure_ascii=False, indent=2)}\n\nAGENTES:\n{deliveries}\n\nREVISÃO:\n{revision}\n\nProduza uma resposta prática com conclusão e próximos passos.",
        0.25,
    )


def execute_engine(objective, agents):
    started = datetime.now()
    tasks, plan_raw = plan_mission(objective, agents)
    by_id = {t.get("agente"): t for t in tasks if isinstance(t, dict)}
    results = {}
    selected = [a for a in agents if a["id"] in by_id]
    max_workers = min(max(1, st.session_state.settings["max_workers"]), max(1, len(selected)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(run_worker, a, objective, by_id[a["id"]].get("tarefa", ""), plan_raw): a["nome"]
            for a in selected
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = f"ERRO: {exc}"

    revision = review(objective, tasks, results) if st.session_state.settings["auto_review"] else "Revisão desativada."
    final = synthesize(objective, tasks, results, revision)
    finished = datetime.now()
    report = {
        "inicio": started.strftime("%d/%m/%Y %H:%M:%S"),
        "fim": finished.strftime("%d/%m/%Y %H:%M:%S"),
        "modelo": MODEL,
        "missao": objective,
        "tarefas": tasks,
        "resultados": results,
        "revisao": revision,
        "final": final,
    }
    st.session_state.mission_history.insert(0, report)
    return report


async def make_audio(text, filename):
    await edge_tts.Communicate(text, "pt-BR-AntonioNeural").save(filename)

# ============================================================
# UI
# ============================================================

st.title("🤖 Jarvis Agent")
st.caption(f"Motor multiagente • {MODEL}")

with st.sidebar:
    st.header("⚙️ Configuração")
    st.session_state.settings["max_workers"] = st.slider("Agentes em paralelo", 1, 10, st.session_state.settings["max_workers"])
    st.session_state.settings["auto_review"] = st.checkbox("Revisor automático", value=st.session_state.settings["auto_review"])

    st.divider()
    st.header("👥 Equipe")
    for i, agent in enumerate(st.session_state.agents):
        with st.expander(f"{agent['nome']}"):
            st.write(agent["especialidade"])
            st.caption("Skills: " + ", ".join(agent.get("skills", [])))
            if st.button("Remover", key=f"remove_agent_{i}"):
                st.session_state.agents.pop(i)
                st.rerun()

    with st.expander("➕ Novo agente"):
        new_name = st.text_input("Nome", key="new_agent_name")
        new_spec = st.text_input("Especialidade", key="new_agent_spec")
        skill_choices = list(st.session_state.skills.keys())
        new_skills = st.multiselect("Skills", skill_choices, key="new_agent_skills")
        if st.button("Adicionar agente"):
            if new_name and new_spec:
                slug = re.sub(r"[^a-z0-9]+", "_", new_name.lower()).strip("_") or f"agente_{len(st.session_state.agents)+1}"
                st.session_state.agents.append({"id": slug, "nome": new_name, "especialidade": new_spec, "skills": new_skills})
                st.rerun()

    st.divider()
    st.header("🧠 Skills")
    st.caption("Skills são instruções carregadas apenas para os agentes que precisam delas.")
    for name in st.session_state.skills:
        st.write("• " + name)

    with st.expander("➕ Criar skill"):
        skill_name = st.text_input("Nome da skill", key="skill_name")
        skill_content = st.text_area("Instruções", key="skill_content", height=120)
        if st.button("Salvar skill"):
            if skill_name and skill_content:
                slug = re.sub(r"[^a-z0-9]+", "_", skill_name.lower()).strip("_")
                st.session_state.skills[slug] = skill_content
                st.rerun()

    st.divider()
    st.header("🧠 Memória da sessão")
    memory_item = st.text_input("Adicionar memória")
    if st.button("Guardar memória") and memory_item:
        st.session_state.memory.append(memory_item)
        st.rerun()

    st.divider()
    st.caption("Próxima etapa: memória persistente / Honcho, ferramentas e canais.")

# Tabs
chat_tab, team_tab, history_tab = st.tabs(["💬 Chat", "🧩 Motor Multiagente", "📜 Histórico"])

with chat_tab:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Fale com o Jarvis..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Chefe coordenando a equipe..."):
                try:
                    report = execute_engine(prompt, st.session_state.agents)
                    answer = report["final"]
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})

                    audio_file = "/tmp/jarvis_resposta.mp3"
                    try:
                        asyncio.run(make_audio(answer, audio_file))
                        st.audio(audio_file, format="audio/mp3", autoplay=True)
                    except Exception as audio_error:
                        st.caption(f"Áudio indisponível nesta resposta: {audio_error}")
                except Exception as exc:
                    st.error(f"Erro no motor: {exc}")

with team_tab:
    st.subheader("🧩 Motor Multiagente")
    st.write("A missão passa pelo Chefe, é distribuída aos especialistas em paralelo e termina no Revisor.")
    cols = st.columns(4)
    cols[0].metric("Agentes", len(st.session_state.agents))
    cols[1].metric("Skills", len(st.session_state.skills))
    cols[2].metric("Memórias", len(st.session_state.memory))
    cols[3].metric("Missões", len(st.session_state.mission_history))

    st.divider()
    st.markdown("### Equipe ativa")
    for agent in st.session_state.agents:
        st.markdown(f"**{agent['nome']}** — {agent['especialidade']}")
        st.caption("Skills: " + (", ".join(agent.get("skills", [])) or "nenhuma"))

    if st.session_state.mission_history:
        last = st.session_state.mission_history[0]
        st.divider()
        st.markdown("### Última missão")
        st.info(last["missao"])
        st.markdown("#### Plano/tarefas")
        st.json(last["tarefas"])
        st.markdown("#### Revisão")
        st.markdown(last["revisao"])

with history_tab:
    st.subheader("📜 Histórico de missões")
    if not st.session_state.mission_history:
        st.info("Nenhuma missão executada ainda.")
    for i, item in enumerate(st.session_state.mission_history):
        with st.expander(f"#{i+1} • {item['inicio']} • {item['missao'][:80]}"):
            st.markdown("### Resultado final")
            st.markdown(item["final"])
            st.markdown("### Revisão")
            st.markdown(item["revisao"])
            st.markdown("### Entregas")
            for name, result in item["resultados"].items():
                st.markdown(f"#### {name}")
                st.markdown(result)
