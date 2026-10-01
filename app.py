import os
import asyncio
import streamlit as st
from openai import OpenAI
import edge_tts

# 1. Configuração do OpenRouter (Usa a biblioteca da OpenAI apontando pro OpenRouter)
client = OpenAI(git status
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

# 2. Configuração visual da página
st.set_page_config(page_title="Jarvis", page_icon="🤖")
st.title("🤖 Jarvis Interface Web")

# 3. Memória temporária da conversa na tela
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Caixa de texto para o usuário digitar
if prompt := st.chat_input("Fale com o Jarvis..."):
    # Mostra o que você digitou
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Prepara o comportamento do Jarvis + histórico
    mensagens_api = [
        {"role": "system", "content": "Você é o Jarvis. Responda em português, de forma direta, inteligente e levemente sarcástica."}
    ]
    mensagens_api.extend(st.session_state.messages)

    # 5. Envia pro OpenRouter e gera a resposta
    with st.chat_message("assistant"):
        try:
            # Usando um modelo poderoso e 100% gratuito do OpenRouter
            response = client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free", 
                messages=mensagens_api,
            )
            
            resposta_ia = response.choices[0].message.content
            st.markdown(resposta_ia)
            st.session_state.messages.append({"role": "assistant", "content": resposta_ia})

            # 6. Gera e toca o áudio da resposta na mesma hora
            arquivo_audio = "resposta.mp3"
            async def gerar_audio():
                communicate = edge_tts.Communicate(resposta_ia, "pt-BR-AntonioNeural")
                await communicate.save(arquivo_audio)
            
            asyncio.run(gerar_audio())
            st.audio(arquivo_audio, format="audio/mp3", autoplay=True)
            
        except Exception as e:
            st.error(f"Erro de conexão: {e}")