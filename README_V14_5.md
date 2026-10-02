# Jarvis V14.5 — File & Document Center

Evolução sobre a V14.0 Device & App Control.

## Recursos
- File Center no Command Center
- Listagem de arquivos dentro de `~/Jarvis`
- Busca recursiva por nome/extensão
- Importação de documentos/arquivos de até 8 MB
- Exportação de arquivos de até 8 MB para o navegador
- Criação de ZIP de arquivo/pasta
- Informações/preview para documentos de texto
- Workspaces em `~/Jarvis/Projetos/<nome>` com Documentos, Arquivos, Exports, Imports e Notas
- Multi-PC por dispositivo alvo
- Permission Manager aplicado às novas ações
- Sem shell remoto e sem acesso fora de `~/Jarvis`

## Formatos de importação
PDF, DOCX, XLSX/XLS, CSV, TXT, MD, JSON, HTML/XML, RTF, PPTX/PPT, PNG/JPG/JPEG/WEBP e ZIP.

## Segurança
- `upload_file`, `create_zip` e `create_workspace` são risco médio e passam pela política de aprovação quando configurada.
- `download_file`, `document_info` e `search_files` são leitura/consulta.
- Exclusão continua protegida e bloqueada por padrão.


## V14.5.1 — Correção + modo rápido
- Corrigido `NameError` causado por `unicodeode/unidecode`; agora usa apenas `unicodedata`, sem dependência externa.
- Comandos do PC não chamam o LLM para gerar a confirmação: a resposta é montada localmente após o resultado real do agente.
- Polling do Local Agent reduzido de 1s para 0,2s.
- Honcho não é consultado em toda mensagem; só em mensagens relacionadas à memória.
- Honcho não salva todo turno por padrão; use `HONCHO_SAVE_ALL_TURNS=1` se quiser esse comportamento.
- Voz fica desligada por padrão para não atrasar a resposta; pode ativar no painel Voz ou usar `JARVIS_VOICE_DEFAULT=1`.
- `OPENROUTER_MAX_TOKENS` controla o tamanho máximo das respostas (padrão 600).
- Estado compartilhado é atualizado no máximo a cada 8 segundos para reduzir leituras de rede.


## V14.5.3 — Command Reliability
- Build fingerprint: `14.5.3-command-reliability`.
- Chrome/Edge launch definitions are part of the Local Agent contract.
- Live heartbeat is authoritative for the fast "computadores conectados" query; stale persisted devices no longer override a live agent.
- After deployment, restart `local_agent/start_agent.bat` so the PC agent reports V14.5.3.
