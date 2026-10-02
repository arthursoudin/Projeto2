"""Jarvis V12.8 - Computer Agent.

Agente de computador com planejamento determinístico, execução por allowlist e
verificação de pós-condição. Não executa shell arbitrário nem ações destrutivas.
"""
from __future__ import annotations

from pc_control import parse_pc_commands, CONFIRM_ACTIONS, describe_step

# Ações que o Computer Agent pode usar sem confirmação.
SAFE_ACTIONS = {
    'open_app', 'open_folder', 'open_file', 'open_url', 'search_web',
    'create_folder', 'create_file', 'append_file', 'read_file', 'list_files',
    'move_path', 'copy_path', 'rename_path', 'system_info', 'read_log',
    'schedule_add', 'schedule_list', 'schedule_toggle', 'schedule_remove'
}

BLOCKED_ACTIONS = set(CONFIRM_ACTIONS) | {'schedule_invalid'}


def plan_instruction(instruction: str):
    """Converte uma instrução em um plano seguro usando o parser determinístico."""
    steps = parse_pc_commands(instruction or '')
    if not steps:
        return None, 'Não consegui transformar a instrução em ações do computador.'
    for action, params in steps:
        if action in BLOCKED_ACTIONS or action not in SAFE_ACTIONS:
            return None, f'Ação não permitida pelo Computer Agent: {action}.'
    return steps, ''


def _verify(action, params, result):
    """Verificação de pós-condição baseada no resultado real do agente local."""
    if not isinstance(result, dict):
        return {'ok': False, 'tipo': 'resultado_invalido', 'detalhe': 'O agente local não retornou um objeto.'}
    if not result.get('ok'):
        return {'ok': False, 'tipo': 'execucao', 'detalhe': result.get('error') or result.get('message') or 'Ação falhou.'}

    # Para operações de filesystem, o agente local já devolve flags/path reais.
    if action in {'create_folder', 'create_file'} and result.get('created') is not True:
        return {'ok': False, 'tipo': 'pos_condicao', 'detalhe': 'A operação informou sucesso, mas não confirmou criação.'}
    if action in {'move_path', 'copy_path', 'rename_path'} and result.get('ok') is not True:
        return {'ok': False, 'tipo': 'pos_condicao', 'detalhe': 'A operação não confirmou o novo estado.'}
    if action == 'system_info' and not result.get('computer'):
        return {'ok': False, 'tipo': 'pos_condicao', 'detalhe': 'Informações do computador incompletas.'}
    return {'ok': True, 'tipo': 'resultado_real', 'detalhe': 'Resultado aceito como pós-condição.'}


def execute(instruction, runner):
    """Executa o plano em sequência. runner(action, params) -> {'ok', 'result'|'error'}."""
    steps, error = plan_instruction(instruction)
    if not steps:
        return {'ok': False, 'instruction': instruction, 'error': error, 'plan': [], 'trace': []}

    trace = []
    for index, (action, params) in enumerate(steps, 1):
        if action in BLOCKED_ACTIONS:
            trace.append({'step': index, 'action': action, 'ok': False, 'status': 'blocked',
                          'description': describe_step(action, params),
                          'verification': {'ok': False, 'tipo': 'blocked', 'detalhe': 'Exige confirmação ou não é permitido.'}})
            return {'ok': False, 'instruction': instruction, 'plan': steps, 'trace': trace,
                    'error': 'O Computer Agent parou por uma ação que exige confirmação.'}

        response = runner(action, dict(params or {})) or {}
        result = response.get('result') or response.get('error') or response
        verification = _verify(action, params, result)
        item = {
            'step': index,
            'action': action,
            'params': params,
            'description': describe_step(action, params),
            'ok': bool(response.get('ok')) and bool(verification.get('ok')),
            'result': result,
            'verification': verification,
        }
        trace.append(item)
        if not item['ok']:
            return {'ok': False, 'instruction': instruction, 'plan': steps, 'trace': trace,
                    'error': f'Execução interrompida na etapa {index}.'}

    return {'ok': True, 'instruction': instruction, 'plan': steps, 'trace': trace,
            'summary': f'{len(trace)} etapa(s) executada(s) e verificadas.'}
