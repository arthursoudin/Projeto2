import os
import threading
import asyncio
import nest_asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import google.generativeai as genai
import edge_tts
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Permite rodar o bot e o edge-tts sem conflito de threads
nest_asyncio.apply()

# 1. Configurações
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

# 2. Servidor Web Falso (Para o Render não derrubar a aplicação)
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Jarvis Online!")

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# 3. Funções do Bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sistemas online, senhor. Como posso ajudar?")

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensagem = update.message.text
    
    # Pede a resposta pro Gemini
    instrucao = "Você é o Jarvis. Responda em português, de forma curta, direta e um pouco sarcástica."
    resposta_ia = model.generate_content(f"{instrucao}\nUsuário: {mensagem}").text
    
    # Envia o texto
    await update.message.reply_text(resposta_ia)
    
    # Gera o áudio com a voz do Antonio (Microsoft) e envia
    arquivo_audio = f"resposta_{update.message.chat_id}.mp3"
    communicate = edge_tts.Communicate(resposta_ia, "pt-BR-AntonioNeural")
    await communicate.save(arquivo_audio)
    
    with open(arquivo_audio, "rb") as audio:
        await update.message.reply_voice(voice=audio)
        
    os.remove(arquivo_audio) # Limpa o arquivo para economizar espaço

def main():
    # Inicia o servidor web falso em segundo plano
    threading.Thread(target=keep_alive, daemon=True).start()

    # Inicia o Bot do Telegram
    token = os.environ.get("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    
    print("Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()