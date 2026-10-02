# Jarvis V11.9

Interface + IA + memória + tarefas (Render) e um agente local que controla o seu PC
com permissões. Nada de shell livre: cada ação é uma função fixa.

## Como atualizar (3 passos)

1. Extraia este zip **por cima** da sua pasta `Codes` (substituir). O `.git` não é afetado.
2. `git add .` → `git commit -m "v11.9"` → `git push` (o Render faz o deploy sozinho).
3. No PC, abra `local_agent/start_agent.bat`. Na primeira vez ele pergunta a URL do Gateway
   e o token e salva em `config.json`. Depois é só abrir e deixar a janela aberta.

**Variáveis do Render: nada muda** (`OPENROUTER_API_KEY`, `HONCHO_API_KEY`,
`JARVIS_GATEWAY_URL`, `LOCAL_AGENT_TOKEN`). O `setup_agent.bat` não existe mais.

## O que dá para pedir

| Tipo | Exemplos |
|---|---|
| Pastas e arquivos | `crie uma pasta Estudos` · `crie um arquivo notas.txt com o texto olá` · `leia o arquivo notas.txt` · `escreva no arquivo notas.txt o texto mais uma linha` · `liste os arquivos da pasta Estudos` |
| Organizar | `mova o arquivo notas.txt para a pasta Estudos` · `copie notas.txt para copia.txt` · `renomeie o arquivo notas.txt para ideias.txt` |
| Apagar (pede confirmação) | `apague o arquivo notas.txt` → o Jarvis pergunta → `sim` |
| Aplicativos | `abra o vs code` · bloco de notas · calculadora · paint · word · excel · powerpoint · gerenciador de tarefas · explorador |
| Navegador | `abra o youtube` · `abra o site github.com` · `pesquise gatos no google` · `no youtube pesquise lofi` |
| Abrir com programa | `abra a pasta Estudos no vs code` · `abra o arquivo notas.txt no bloco de notas` |
| Sistema | `informações do meu sistema` · `quanta RAM eu tenho?` |
| Compostos | `crie uma pasta Projetos e dentro dela um arquivo ideias.txt, depois abra a pasta no vs code` |

Para encadear use **"e depois"**, **"depois"**, **"em seguida"** ou `;`.
Para colocar algo em uma pasta recém-criada diga **"dentro dela"**; sem isso fica na raiz.

## Regras de segurança

- Tudo acontece dentro de `C:\Users\<você>\Jarvis`. Caminhos com `..` ou fora dela são recusados.
- **Apagar não apaga de verdade**: o item vai para `Jarvis\.lixeira` e pode ser restaurado.
- Não cria, renomeia nem abre `.exe .bat .cmd .ps1 .vbs .js .lnk` e similares.
- Sites: só `http/https`. Aplicativos: só a lista acima.
- Tudo o que o agente faz fica em `Jarvis\.jarvis_agente.log` (também na aba **Sistema**).
- Nunca suba `local_agent/config.json` para o GitHub (já está no `.gitignore`).
  Se o token já foi publicado, troque-o no Render e no `config.json`.

## Solução de problemas

- **"O agente local não respondeu"**: a janela do `start_agent.bat` está fechada, ou o token difere do Render.
- **"Token recusado"** no terminal do agente: apague `local_agent/config.json` e abra o `.bat` de novo.
- **VS Code não abre**: instale-o pelo instalador oficial (o agente procura o `Code.exe`).
- O plano free do Render dorme: o primeiro comando depois de um tempo parado pode demorar.

## Arquivos

`app.py` interface · `pc_control.py` interpretador de comandos e permissões ·
`gateway.py` ponte Render ↔ PC · `local_agent/agent.py` executor no Windows
