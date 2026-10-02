"""Jarvis V12.7 — catálogo central de Tools 2.0.

A execução continua protegida pelos handlers existentes em core.py/pc_control.py.
Este módulo fornece um contrato único de descoberta: nome, descrição, categoria,
agentes permitidos e nível de risco. Assim o Planejador e o Dashboard podem
conhecer as ferramentas sem duplicar listas espalhadas pelo projeto.
"""

TOOLS = {
    'calculator': {'nome':'Calculadora','categoria':'utilidade','descricao':'Executa cálculos matemáticos simples.','agentes':['redator','tarefas'],'risco':'baixo'},
    'time': {'nome':'Data e hora','categoria':'utilidade','descricao':'Consulta a data e hora no fuso configurado.','agentes':['redator','tarefas'],'risco':'baixo'},
    'web_search': {'nome':'Pesquisa web','categoria':'internet','descricao':'Pesquisa informações públicas na web.','agentes':['pesquisa','redator'],'risco':'baixo'},
    'memory': {'nome':'Memória','categoria':'memoria','descricao':'Salva informações na memória local.','agentes':['memoria','redator'],'risco':'baixo'},
    'memory_search': {'nome':'Busca na memória','categoria':'memoria','descricao':'Consulta memória disponível ao Jarvis.','agentes':['memoria','redator'],'risco':'baixo'},
    'tasks': {'nome':'Tarefas','categoria':'produtividade','descricao':'Cria e consulta tarefas e prazos.','agentes':['tarefas','redator'],'risco':'baixo'},
    'computer': {'nome':'Computador','categoria':'pc','descricao':'Executa ações permitidas no PC por meio do agente local.','agentes':['pc'],'risco':'moderado'},
    'filesystem': {'nome':'Arquivos','categoria':'pc','descricao':'Cria, lê, lista, move, copia e renomeia arquivos dentro da área segura.','agentes':['pc'],'risco':'moderado'},
    'schedule': {'nome':'Rotinas','categoria':'automacao','descricao':'Cria e controla rotinas permitidas no agente local.','agentes':['pc'],'risco':'moderado'},
}

TRIGGER_MAP = {
    'calculator': ['quanto é','calcule','calcular'],
    'time': ['que horas','horário','horario','data de hoje'],
    'tasks': ['crie uma tarefa','adiciona uma tarefa','adicione uma tarefa','nova tarefa','criar tarefa','me lembre de','lembre de'],
    'memory': ['lembra de','guarde que','memorize'],
    'web_search': ['pesquise','procure na internet','pesquisa na web'],
}

def list_tools():
    return TOOLS.copy()

def get_tool(name):
    return TOOLS.get(str(name).strip().lower())

def tools_for_agent(agent):
    a=str(agent).strip().lower()
    return {k:v for k,v in TOOLS.items() if a in v.get('agentes',[])}

def tool_rows():
    return [
        {'ID':k,'Ferramenta':v['nome'],'Categoria':v['categoria'],'Agentes':', '.join(v['agentes']),'Risco':v['risco']}
        for k,v in TOOLS.items()
    ]
