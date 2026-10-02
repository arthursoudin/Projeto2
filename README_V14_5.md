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
