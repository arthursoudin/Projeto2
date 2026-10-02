"""Monitor opcional do Jarvis.

Este loop é um watchdog local: verifica periodicamente a URL pública do Gateway.
Ele não substitui o UptimeRobot. O UptimeRobot deve monitorar /uptime externamente;
este script é útil para diagnóstico e para manter uma verificação contínua no PC.
"""
import os, time, datetime as dt
import requests

URL=os.getenv('JARVIS_UPTIME_URL','https://SEU-GATEWAY.onrender.com/uptime')
INTERVAL=max(30,int(os.getenv('JARVIS_UPTIME_INTERVAL','300')))

def check():
    started=time.time()
    try:
        r=requests.get(URL,timeout=15)
        ms=round((time.time()-started)*1000)
        try: data=r.json()
        except Exception: data={}
        ok=r.ok and data.get('ok') is True
        print(f"[{dt.datetime.now():%d/%m/%Y %H:%M:%S}] {'ONLINE' if ok else 'ERRO'} HTTP {r.status_code} {ms}ms | {URL}",flush=True)
        return ok
    except Exception as e:
        print(f"[{dt.datetime.now():%d/%m/%Y %H:%M:%S}] OFFLINE | {type(e).__name__}: {e}",flush=True)
        return False

if __name__=='__main__':
    print('JARVIS UPTIME LOOP V12.7')
    print('URL:',URL)
    print('Intervalo:',INTERVAL,'segundos')
    print('Para encerrar: Ctrl+C')
    while True:
        check()
        time.sleep(INTERVAL)
