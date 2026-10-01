import os, json
from pathlib import Path
from fastapi import FastAPI, Request
app=FastAPI(title='Jarvis Gateway',version='10.0')
TASKS_FILE=Path('.jarvis_tasks.json')

def tasks():
    try: return json.loads(TASKS_FILE.read_text(encoding='utf-8')) if TASKS_FILE.exists() else []
    except Exception: return []

@app.get('/')
def root(): return {'service':'jarvis-gateway','version':'10.0'}
@app.get('/health')
def health(): return {'ok':True,'service':'jarvis-gateway','version':'10.0','channels':['whatsapp'],'honcho_configured':bool(os.getenv('HONCHO_API_KEY'))}
@app.get('/webhook')
def verify_webhook(): return {'ok':True,'message':'Webhook endpoint ativo','version':'10.0'}
@app.post('/webhook')
async def webhook(request:Request): return {'ok':True,'received':True,'memory_ready':bool(os.getenv('HONCHO_API_KEY')),'tasks':len(tasks())}
@app.get('/tasks')
def list_tasks(): return {'ok':True,'tasks':tasks()}
