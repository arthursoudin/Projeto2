import os
from fastapi import FastAPI, Request
app=FastAPI(title='Jarvis Gateway',version='9.0')
@app.get('/')
def root(): return {'service':'jarvis-gateway','version':'9.0'}
@app.get('/health')
def health(): return {'ok':True,'service':'jarvis-gateway','version':'9.0','channels':['whatsapp'],'honcho_configured':bool(os.getenv('HONCHO_API_KEY'))}
@app.get('/webhook')
def verify_webhook(): return {'ok':True,'message':'Webhook endpoint ativo'}
@app.post('/webhook')
async def webhook(request:Request): return {'ok':True,'received':True,'memory_ready':bool(os.getenv('HONCHO_API_KEY'))}
