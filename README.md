# Jarvis V12.5

Interface + IA (Render), agente local no seu PC, rotinas agendadas, armazenamento persistente, voz,
dashboard, **WhatsApp** e **equipe de agentes**.

| Versão | O que tem |
|---|---|
| 12.1 | **WhatsApp**: texto e áudio, comandos do PC, tarefas, confirmação de exclusão |
| 12.2 | Voz: microfone e respostas faladas |
| 12.3 | **Dashboard completo**: agente, canais, tarefas, rotinas, armazenamento |
| 12.4 | Rotinas agendadas + armazenamento persistente (Supabase) |
| 12.5 | **Multiagentes**: Planejador + especialistas (`/equipe`) |

## Como atualizar (3 passos)

1. Extraia o zip **por cima** da sua pasta `Codes` (substituir). O `.git` não é afetado.
2. `git add .` → `git commit -m "v12.5"` → `git push`. Faça o deploy do **app** e do **gateway** no Render
   (os dois usam esta pasta; o gateway agora também precisa do `requirements.txt` completo).
3. O `local_agent` **não mudou**: se ele já está aberto, não precisa reiniciar.

Sem configurar nada novo, tudo continua como antes. O WhatsApp é opcional (seção abaixo).

## WhatsApp (V12.1)

Você manda mensagem para o número de teste da Meta e o Jarvis responde, executando no seu PC pelo agente local.
Aceita **texto e áudio** (o áudio é transcrito pelo mesmo Whisper do microfone).

**Configuração (uma vez, uns 15 min)** — também aparece na aba **WhatsApp** do app:

1. Em developers.facebook.com, crie um app **Business** e adicione o produto **WhatsApp**.
2. Em *WhatsApp > Configuração da API*: anote o **ID do número de telefone** (não é o telefone) e adicione o seu
   celular como destinatário de teste.
3. Em *Configurações do app > Básico*: copie a **Chave secreta do app**. Crie um **usuário do sistema** e gere um
   **token permanente** com a permissão `whatsapp_business_messaging` (o token temporário expira em 24 h).
4. No Render, serviço do **gateway**, crie as variáveis:

| Variável | Valor |
|---|---|
| `WHATSAPP_TOKEN` | token permanente |
| `WHATSAPP_PHONE_NUMBER_ID` | ID do número de telefone |
| `WHATSAPP_VERIFY_TOKEN` | um texto qualquer que você inventar |
| `WHATSAPP_APP_SECRET` | chave secreta do app |
| `WHATSAPP_ALLOWED_NUMBERS` | seu número com DDI, ex.: `5511999998888` (vários: separe por vírgula) |
| `OPENROUTER_API_KEY` (e opcional `OPENROUTER_MODEL`) | para o Jarvis conversar |

5. Em *WhatsApp > Configuração > Webhook*: URL `https://SEU-GATEWAY.onrender.com/webhook`, o mesmo
   `WHATSAPP_VERIFY_TOKEN`, e inscreva-se no campo **messages**.
6. Mande **/ajuda** para o número de teste.

**Segurança (importante, o Jarvis controla o seu PC):** só responde a números da lista; só aceita mensagens com
assinatura válida da Meta (**sem `WHATSAPP_APP_SECRET` ele recusa tudo**); apagar sempre pede "sim"; 20 mensagens/min
por número; mensagens repetidas (a Meta reenvia) são ignoradas; o dashboard mostra só número mascarado e tipo, nunca o texto.

**Comandos:** tudo o que você já pede no chat funciona. Atalhos: `/ajuda`, `/tarefas`, `/rotinas`, `/status`, `/equipe <objetivo>`.
Para tarefas e memória serem as mesmas no site e no WhatsApp, use o **mesmo Supabase** nos dois serviços do Render.
O plano grátis do Render dorme: a primeira mensagem depois de um tempo parado pode demorar ~1 min. Se o agente do PC
estiver fechado, o Jarvis avisa em vez de fingir que executou.

## Equipe de agentes (V12.5)

`/equipe organize meus estudos de python: crie a pasta Estudos e uma tarefa para amanhã às 9h`

Um **Planejador** divide o pedido em até 6 etapas e entrega cada uma a um especialista: 🖥️ PC, ✅ Tarefas,
🧠 Memória, 🔎 Pesquisa, ✍️ Redator. Também dispara com "planeje…", "monte um plano…" ou "multiagente". Regras:

- O Planejador só escolhe entre os agentes; o agente do PC recebe uma **frase** e o mesmo interpretador de sempre
  decide a ação, com as mesmas permissões.
- **Equipes nunca apagam nada.** Apagar continua sendo direto com o Jarvis, com confirmação.
- Se uma etapa falha, as seguintes **não rodam** e aparecem como "não executada".
- O relatório é montado a partir dos resultados reais das etapas (sem LLM), então não inventa que algo foi feito.
- A aba **Agentes** mostra a última execução (inclusive as feitas pelo WhatsApp).

## Voz (microfone + respostas faladas)

**Falar com o Jarvis:** na aba Chat, clique no microfone, fale, e envie a gravação. Ele transcreve, executa
(inclusive comandos do PC e o "sim/não" de confirmação) e responde **em voz**. O navegador pede permissão do
microfone na primeira vez.

**Não precisa configurar nada:** a transcrição usa o Whisper pela **OpenRouter**, com a mesma `OPENROUTER_API_KEY`
que o app já usa (modelo padrão `openai/whisper-large-v3`). É pago por segundo de áudio, normalmente frações
de centavo por comando curto; o preço de cada modelo aparece em openrouter.ai/models?output_modalities=transcription.
Se faltar saldo, o app avisa. Opcional, no Render (serviço do app):

| Variável | Para quê |
|---|---|
| `STT_MODEL` | trocar o modelo (nome completo, ex.: `openai/whisper-1`) |
| `STT_PROVIDER=groq` + `GROQ_API_KEY` | usar o Groq (tem plano grátis) em vez da OpenRouter |
| `STT_PROVIDER=openai` + `OPENAI_API_KEY` | usar a OpenAI direto |

**Respostas faladas:** na barra lateral, **🔊 Voz**: liga/desliga, escolhe a voz (Antonio ou Francisca) e a
velocidade. O Jarvis lê só o essencial: sem markdown, emojis, links ou código, e corta respostas longas
("o restante está na tela"). Quando você fala, ele sempre responde em voz.
Dica: o Whisper às vezes erra nomes. Se ele criar uma pasta com nome estranho, diga "renomeie".

## Dashboard

Aba **Dashboard**: agente online/offline, CPU, RAM, disco, tempo ligado, gráfico de CPU/RAM, rotinas ativas
e a próxima, **canais (WhatsApp: ativo, mensagens hoje, último contato, atividade recente)**, **próximas tarefas**,
armazenamento, Honcho, microfone, últimas ações no PC, botões **Ver rotinas do PC** e **Ver log do agente**.
O agente envia um "batimento" a cada 10 s; a página atualiza sozinha a cada 10 s e **pausa após 10 min
sem uso** (clique em Retomar). Se aparecer "offline", o `start_agent.bat` está fechado.

## Persistência com Supabase (opcional, grátis)

1. Crie um projeto em supabase.com (região São Paulo).
2. Em **SQL Editor**, cole e rode:

```sql
create table if not exists jarvis_kv (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz default now()
);
alter table jarvis_kv enable row level security;
```

3. Em **Settings → API Keys**, copie a **Project URL** e a **secret key** (`sb_secret_...`).
4. No Render, serviço do **app** (não o gateway), adicione:
   `SUPABASE_URL` = a Project URL · `SUPABASE_KEY` = a secret key.

A barra lateral mostra se está conectado. Na primeira leitura, as tarefas e memórias que já
existirem no arquivo local são enviadas para o Supabase automaticamente.
A secret key é só do servidor: nunca coloque no GitHub nem em arquivo do projeto.
Projetos grátis do Supabase podem pausar após muito tempo sem uso; é só reativar no painel.

## Rotinas (automação no PC)

As rotinas ficam salvas **no seu PC** (`Jarvis\.jarvis_agenda.json`) e rodam pelo agente local,
mesmo com o app fechado ou o Render dormindo. O agente precisa estar aberto.

| Peça no chat | O que acontece |
|---|---|
| `todo dia às 9h abra o vs code` | todo dia, 09:00 |
| `de segunda a sexta às 8h30 abra a pasta Estudos` | dias úteis |
| `toda segunda e quarta às 19h abra o youtube` | dias escolhidos |
| `nos fins de semana às 10h abra o spotify` | sábado e domingo |
| `daqui a 10 minutos abra a calculadora` | uma vez, em 10 min |
| `amanhã às 7h30 abra o site github.com` | uma vez, amanhã |
| `às 18h abra o paint` | uma vez, hoje (ou amanhã se já passou) |
| `a cada 30 minutos abra o navegador` | intervalo (mínimo 5 min) |
| `liste minhas rotinas` | mostra números, horários e último resultado |
| `pause a rotina 2` · `ative a rotina 2` · `cancele a rotina 2` | gerenciar |

Dá para encadear passos: `todo dia às 9h abra o vs code e depois abra o youtube`.
A aba **Automações** também lista e controla as rotinas.

Regras: rotinas **não apagam nada** (apagar exige confirmação na hora), no máximo 8 passos e
30 rotinas. Se o PC estava desligado no horário, a execução é pulada e aparece como "perdida"
(a próxima ocorrência segue normal). "Me lembre de..." continua sendo tarefa, não rotina.

## Pedidos do PC (V11.9, continua valendo)

Pastas e arquivos (criar, ler, escrever, listar, mover, copiar, renomear), apagar com
confirmação (vai para `Jarvis\.lixeira`), aplicativos, navegador, informações do sistema e
comandos compostos com "e depois". Tudo dentro de `C:\Users\<você>\Jarvis`; o log fica em
`Jarvis\.jarvis_agente.log`. Nunca suba `local_agent/config.json` para o GitHub.

## Solução de problemas

- **Microfone não aparece**: falta `OPENROUTER_API_KEY`. **"Sem saldo"**: adicione créditos na OpenRouter. **"Modelo não encontrado"**: ajuste `STT_MODEL`.
- **Dashboard "offline"**: abra o `start_agent.bat`; o plano grátis do Render demora a acordar no primeiro acesso.
- **Rotina não rodou**: o `start_agent.bat` estava fechado, ou o horário passou com o PC desligado (veja "perdida" em `liste minhas rotinas`).
- **"⚠️ Armazenamento: arquivo"**: Supabase não configurado; os dados somem quando o Render reinicia.
- **"Falha: tabela não existe"**: rode o SQL do passo 2.
- **"Chave recusada"**: confira `SUPABASE_KEY` (use a secret key, sem aspas nem espaços).

- **Meta não valida o webhook**: confira que `WHATSAPP_VERIFY_TOKEN` é idêntico nos dois lados e que o gateway já acordou (abra `/health`).
- **Mensagem chega e nada responde**: veja a aba WhatsApp. "Assinatura inválida" = `WHATSAPP_APP_SECRET` errado/faltando. Sem log de
  mensagem = número fora de `WHATSAPP_ALLOWED_NUMBERS`. Erro de token = gere um token permanente.
- **Erro 131030 / 131047**: número de teste não adicionado como destinatário / passou 24 h sem você escrever (mande um "oi").

## Arquivos

`app.py` interface · `core.py` cérebro sem Streamlit (usado pelo WhatsApp e pela equipe) · `agents.py` multiagentes ·
`whatsapp.py` canal WhatsApp · `pc_control.py` comandos, permissões e agendamento · `store.py` armazenamento ·
`voice_io.py` microfone e texto falado · `gateway.py` ponte Render ↔ PC + webhook do WhatsApp ·
`local_agent/agent.py` executor e agendador no Windows · `tests/` testes (`python -m unittest discover -s tests`)

## Mudanças da V12.5 (além do que está acima)

- **Fuso horário**: tarefas e "que horas são" usavam UTC (o Render roda em UTC); agora usam `America/Sao_Paulo`
  (mude com `JARVIS_TZ`). Tarefas antigas continuam válidas.
- **Horário "às 10h"** (sem minutos) era ignorado e a tarefa saía às 09:00; corrigido. Também entende "às 7 da noite".
- "depois de amanhã" era lido como "amanhã"; corrigido.
- Calculadora recusa `**` (uma conta como `9**9**9` travava o servidor).
- Tarefas e memória são relidas do armazenamento a cada interação (para enxergar o que o WhatsApp criou); se a leitura
  falhar, a sessão mantém o que tem, nunca zera.
- `GET /tasks` do gateway agora exige o token do agente (antes era público).

## Limites conhecidos

- O app Streamlit **não tem senha**: quem souber a URL pode usá-lo. Está previsto para a V12.9 (Segurança); até lá, não divulgue a URL.
- O WhatsApp responde só em texto (a transcrição de áudio de entrada funciona).
- A memória Honcho ainda não é consultada pelo canal WhatsApp (ele usa memória local, tarefas e histórico).
