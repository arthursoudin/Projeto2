"""JARVIS LOCAL AGENT V11.9

Roda no seu Windows como usuário normal. Busca comandos no Gateway, executa
apenas ações permitidas dentro de ~/Jarvis e devolve o resultado real.
Não existe shell remoto: cada ação é uma função fixa abaixo.
"""
import datetime
from datetime import timedelta
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import uuid
import getpass
import base64
import zipfile
from urllib.parse import quote_plus, urlparse

import requests

VERSION = "19.0.0"
BASE_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

JARVIS_HOME = pathlib.Path.home() / "Jarvis"
JARVIS_HOME.mkdir(parents=True, exist_ok=True)
TRASH = JARVIS_HOME / ".lixeira"
LOG_FILE = JARVIS_HOME / ".jarvis_agente.log"

MAX_READ = 4000          # caracteres devolvidos por read_file
MAX_WRITE = 100_000      # caracteres aceitos por create_file/append_file
BLOCKED_EXT = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".lnk", ".reg", ".hta", ".jar", ".dll", ".cpl",
}
INVALID_CHARS = '<>:"|?*'
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


# ------------------------------------------------------------------ config
def load_config():
    cfg = {"gateway_url": "", "token": "", "poll_seconds": 0.35, "device_id": ""}
    try:
        if CONFIG_FILE.exists():
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
    except Exception as e:
        print(f"[CONFIG] Erro ao ler config.json: {e}")
    cfg["gateway_url"] = (os.getenv("JARVIS_GATEWAY_URL") or cfg.get("gateway_url") or "").strip().rstrip("/")
    cfg["token"] = (os.getenv("LOCAL_AGENT_TOKEN") or cfg.get("token") or "").strip()
    try:
        cfg["poll_seconds"] = max(0.25, float(cfg.get("poll_seconds", 0.35)))
    except Exception:
        cfg["poll_seconds"] = 0.35
    return cfg


def first_run_setup(cfg):
    """Se faltar URL/token, pergunta uma vez e salva no config.json."""
    if cfg["gateway_url"] and cfg["token"]:
        return cfg
    print("Primeira execução: vamos configurar (só uma vez).\n")
    url = input("URL do Gateway (ex: https://projeto2-2-xxxx.onrender.com): ").strip().rstrip("/")
    token = input("LOCAL_AGENT_TOKEN (o mesmo que está no Render): ").strip()
    if url and not url.startswith("http"):
        url = "https://" + url
    cfg.update({"gateway_url": url, "token": token})
    CONFIG_FILE.write_text(
        json.dumps({"gateway_url": url, "token": token, "poll_seconds": cfg["poll_seconds"], "device_id": cfg.get("device_id", "")}, indent=2),
        encoding="utf-8",
    )
    print("\n[OK] Configuração salva em config.json\n")
    return cfg


CONFIG = load_config()
if not str(CONFIG.get("device_id") or "").strip():
    CONFIG["device_id"] = str(uuid.uuid5(
        uuid.NAMESPACE_DNS,
        f"jarvis:{platform.node()}:{getpass.getuser()}"
    ))


def headers():
    return {"X-Agent-Token": CONFIG["token"], "X-Device-ID": CONFIG.get("device_id", ""), "Content-Type": "application/json"}


# ------------------------------------------------------------ segurança
def _check_part(part):
    part = part.strip()
    if not part or part in (".", ".."):
        raise ValueError('Caminho inválido (vazio, "." ou "..").')
    if any(c in part for c in INVALID_CHARS) or any(ord(c) < 32 for c in part):
        raise ValueError('O nome contém caracteres que o Windows não aceita: < > : " | ? *')
    part = part.rstrip(". ")
    if not part:
        raise ValueError("Nome inválido.")
    if part.split(".")[0].upper() in RESERVED:
        raise ValueError(f"Nome reservado do Windows: {part}")
    return part


def safe_path(name):
    """Resolve um caminho garantindo que fica dentro de ~/Jarvis."""
    raw = str(name or "").strip()
    if raw in ("", "."):
        return JARVIS_HOME.resolve()
    p = pathlib.Path(raw)
    if p.is_absolute():
        cand = p.resolve()
    else:
        parts = [_check_part(x) for x in raw.replace("\\", "/").split("/") if x.strip() not in ("", ".")]
        cand = JARVIS_HOME.joinpath(*parts).resolve()
    try:
        cand.relative_to(JARVIS_HOME.resolve())
    except ValueError:
        raise ValueError("Acesso fora da pasta Jarvis não permitido.")
    return cand


def _protect(target):
    home = JARVIS_HOME.resolve()
    if target == home or target in (TRASH.resolve(), LOG_FILE.resolve()):
        raise ValueError("Esse item é protegido e não pode ser alterado.")


def _check_ext(target):
    if target.suffix.lower() in BLOCKED_EXT:
        raise ValueError(f"Arquivos {target.suffix} (executáveis/scripts) não são permitidos por segurança.")


def _ok(message, **extra):
    return {"ok": True, "message": message, **extra}


def _err(message):
    return {"ok": False, "error": message}


# ---------------------------------------------------------------- abrir
def _find_vscode():
    cands = [
        pathlib.Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        pathlib.Path(os.getenv("ProgramFiles", "")) / "Microsoft VS Code" / "Code.exe",
    ]
    w = shutil.which("code")
    if w:
        cands.append(pathlib.Path(w).resolve().parent.parent / "Code.exe")
    for c in cands:
        if c.exists():
            return str(c)
    return None


def _startfile(target):
    if not hasattr(os, "startfile"):
        raise RuntimeError("Abrir arquivos/pastas só funciona no Windows.")
    os.startfile(str(target))


def _open_with(target, app):
    if app == "vscode":
        exe = _find_vscode()
        if not exe:
            raise RuntimeError("VS Code não encontrado. Instale-o ou abra pelo menu Iniciar.")
        subprocess.Popen([exe, str(target)])
    elif app == "notepad":
        subprocess.Popen(["notepad.exe", str(target)])
    else:
        _startfile(target)


APP_DEFINITIONS = {
    "notepad": {"label": "Bloco de Notas", "kind": "popen", "target": ["notepad.exe"], "aliases": ["notepad", "bloco de notas"]},
    "calculator": {"label": "Calculadora", "kind": "popen", "target": ["calc.exe"], "aliases": ["calculadora", "calculator"]},
    "paint": {"label": "Paint", "kind": "popen", "target": ["mspaint.exe"], "aliases": ["paint"]},
    "taskmgr": {"label": "Gerenciador de Tarefas", "kind": "popen", "target": ["taskmgr.exe"], "aliases": ["gerenciador de tarefas", "task manager"]},
    "word": {"label": "Microsoft Word", "kind": "startfile", "target": "winword", "aliases": ["word", "microsoft word"]},
    "excel": {"label": "Microsoft Excel", "kind": "startfile", "target": "excel", "aliases": ["excel", "microsoft excel"]},
    "powerpoint": {"label": "Microsoft PowerPoint", "kind": "startfile", "target": "powerpnt", "aliases": ["powerpoint", "power point"]},
    "chrome": {"label": "Google Chrome", "kind": "exe", "target": ["chrome.exe"], "aliases": ["chrome", "google chrome"]},
    "edge": {"label": "Microsoft Edge", "kind": "exe", "target": ["msedge.exe"], "aliases": ["edge", "microsoft edge"]},
    "vscode": {"label": "Visual Studio Code", "kind": "vscode", "target": [], "aliases": ["vs code", "vscode", "visual studio code"]},
    "dbeaver": {"label": "DBeaver", "kind": "exe_candidates", "target": ["dbeaver.exe"], "aliases": ["dbeaver"]},
    "intellij": {"label": "IntelliJ IDEA", "kind": "exe_candidates", "target": ["idea64.exe", "idea.exe"], "aliases": ["intellij", "intellij idea", "idea"]},
    "pgadmin": {"label": "pgAdmin", "kind": "exe_candidates", "target": ["pgAdmin4.exe", "pgadmin4.exe"], "aliases": ["pgadmin", "pgadmin4"]},
    "obsidian": {"label": "Obsidian", "kind": "exe_candidates", "target": ["Obsidian.exe"], "aliases": ["obsidian"]},
}

# Compatibilidade com módulos antigos que consultam APPS.
APPS = {k: (v["kind"], v["target"]) for k, v in APP_DEFINITIONS.items() if v["kind"] in {"popen", "startfile"}}

def _find_app_exe(candidates):
    for name in candidates or []:
        found = shutil.which(name)
        if found:
            return found
    roots = [
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
    ]
    # Procuramos somente em diretórios de instalação conhecidos; sem varrer o disco inteiro.
    known = []
    la=os.environ.get('LOCALAPPDATA','')
    pf=os.environ.get('PROGRAMFILES','')
    pfx=os.environ.get('PROGRAMFILES(X86)','')
    known += [os.path.join(la,'Google','Chrome','Application'),
              os.path.join(pf,'Google','Chrome','Application'),
              os.path.join(pfx,'Google','Chrome','Application'),
              os.path.join(la,'Microsoft','Edge','Application'),
              os.path.join(pf,'Microsoft','Edge','Application'),
              os.path.join(pfx,'Microsoft','Edge','Application')]
    for base in known:
        if not os.path.isdir(base):
            continue
        for name in candidates or []:
            direct=os.path.join(base,name)
            if os.path.isfile(direct):
                return direct
    for root in [r for r in roots if r]:
        for rel in ("Google/Chrome/Application", "Microsoft/Edge/Application", "DBeaver", "JetBrains", "PostgreSQL", "Obsidian"):
            base = os.path.join(root, rel)
            if not os.path.isdir(base):
                continue
            for name in candidates or []:
                direct = os.path.join(base, name)
                if os.path.isfile(direct):
                    return direct
    return None

def list_apps():
    rows=[]
    for key, spec in APP_DEFINITIONS.items():
        available = False
        detail = ''
        if spec['kind'] == 'vscode':
            available = bool(_find_vscode())
            detail = _find_vscode() or ''
        elif spec['kind'] == 'popen':
            available = bool(shutil.which(spec['target'][0]))
        elif spec['kind'] == 'startfile':
            available = True  # Windows resolve via associação/Office; abertura confirma no runtime.
        else:
            path = _find_app_exe(spec['target']); available = bool(path); detail = path or ''
        rows.append({'id': key, 'name': spec['label'], 'available': available, 'path': detail, 'aliases': spec['aliases']})
    return {'ok': True, 'applications': rows, 'count': len(rows)}

def open_app(app):
    app = str(app or '').lower().strip()
    if app == 'browser':
        app = 'chrome'
    spec = APP_DEFINITIONS.get(app)
    if not spec:
        # aliases
        for key, item in APP_DEFINITIONS.items():
            if app in item.get('aliases', []):
                spec = item; app = key; break
    if not spec:
        allowed=', '.join(APP_DEFINITIONS.keys())
        return _err(f"Aplicativo não permitido: {app}. Permitidos nesta versão: {allowed}. Agente V{VERSION}.")
    try:
        kind, target = spec['kind'], spec['target']
        if kind == 'vscode':
            exe = _find_vscode()
            if not exe: return _err("VS Code não encontrado. Verifique se está instalado.")
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif kind == 'popen':
            subprocess.Popen(target, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif kind == 'startfile':
            _startfile(target)
        else:
            exe = _find_app_exe(target)
            if not exe: return _err(f"{spec['label']} não foi encontrado neste computador.")
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return _ok(f"Aplicativo '{spec['label']}' aberto.")
    except FileNotFoundError:
        return _err(f"O aplicativo '{spec['label']}' não foi encontrado neste computador.")
    except Exception as e:
        return _err(f"Erro ao abrir '{spec['label']}': {e}")

def open_folder(name="", app=None):
    try:
        target = safe_path(name)
        if not target.is_dir():
            return _err(f"A pasta não existe: {target}")
        _open_with(target, app)
        return _ok(f"Pasta aberta: {target}", path=str(target))
    except Exception as e:
        return _err(f"Erro ao abrir pasta: {e}")


def open_file(name, app=None):
    try:
        target = safe_path(name)
        if not target.is_file():
            return _err(f"O arquivo não existe: {target}")
        _check_ext(target)
        _open_with(target, app)
        return _ok(f"Arquivo aberto: {target}", path=str(target))
    except Exception as e:
        return _err(f"Erro ao abrir arquivo: {e}")


def open_url(url):
    try:
        url = str(url or "").strip()
        if "://" not in url:
            if not re.match(r"^[\w.-]+\.[a-z]{2,}(:\d+)?(/.*)?$", url, re.I):
                return _err("Link inválido.")
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return _err("Só links http/https são permitidos.")
        webbrowser.open(url)
        return _ok(f"Site aberto: {url}", url=url)
    except Exception as e:
        return _err(f"Erro ao abrir site: {e}")


def search_web(query, engine="google"):
    query = str(query or "").strip()
    if not query:
        return _err("Pesquisa vazia.")
    base = "https://www.youtube.com/results?search_query=" if engine == "youtube" else "https://www.google.com/search?q="
    return open_url(base + quote_plus(query))


# -------------------------------------------------------------- arquivos
def create_folder(name):
    try:
        target = safe_path(name)
        _protect(target)
        if target.exists():
            if target.is_dir():
                return _ok(f"A pasta já existe: {target}", path=str(target), created=False)
            return _err(f"Já existe um arquivo com esse nome: {target}")
        target.mkdir(parents=True, exist_ok=False)
        return _ok(f"Pasta criada com sucesso: {target}", path=str(target), created=True)
    except Exception as e:
        return _err(f"Erro ao criar pasta: {e}")



MAX_BINARY = 8 * 1024 * 1024
ALLOWED_DOCUMENT_EXT = {
    ".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".md", ".json", ".html", ".htm",
    ".xml", ".rtf", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".webp", ".zip"
}

def _check_document_ext(target):
    _check_ext(target)
    if target.suffix.lower() not in ALLOWED_DOCUMENT_EXT:
        raise ValueError(f"Formato não permitido no File Center: {target.suffix or '(sem extensão)'}")

def upload_file(name, data_b64, overwrite=False):
    try:
        target = safe_path(name)
        _protect(target); _check_document_ext(target)
        if not target.parent.is_dir():
            return _err(f"A pasta de destino não existe: {target.parent}")
        if target.exists() and not overwrite:
            return _err(f"O arquivo já existe: {target}")
        raw = base64.b64decode(str(data_b64 or ''), validate=True)
        if len(raw) > MAX_BINARY:
            return _err(f"Arquivo grande demais (máximo {MAX_BINARY // (1024*1024)} MB).")
        target.write_bytes(raw)
        return _ok(f"Arquivo importado: {target.name}", path=str(target), bytes=len(raw))
    except Exception as e:
        return _err(f"Erro ao importar arquivo: {e}")

def download_file(name):
    try:
        target = safe_path(name)
        if not target.is_file(): return _err(f"O arquivo não existe: {target}")
        size = target.stat().st_size
        if size > MAX_BINARY: return _err(f"Arquivo grande demais para exportar (máximo {MAX_BINARY // (1024*1024)} MB).")
        return _ok(f"Arquivo pronto para exportação: {target.name}", path=str(target), name=target.name, bytes=size, data_b64=base64.b64encode(target.read_bytes()).decode('ascii'))
    except Exception as e:
        return _err(f"Erro ao exportar arquivo: {e}")

def create_zip(src, dst):
    try:
        source = safe_path(src); target = safe_path(dst)
        _protect(source); _protect(target)
        if not source.exists(): return _err(f"Origem não existe: {source}")
        if target.suffix.lower() != '.zip': raise ValueError('O destino precisa terminar em .zip')
        _check_ext(target)
        if target.exists(): return _err(f"Já existe: {target}")
        if not target.parent.is_dir(): return _err(f"A pasta de destino não existe: {target.parent}")
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            if source.is_file(): zf.write(source, arcname=source.name)
            else:
                for item in source.rglob('*'):
                    if item.is_file() and TRASH not in item.parents:
                        zf.write(item, arcname=str(item.relative_to(source)))
        return _ok(f"Arquivo ZIP criado: {target.name}", path=str(target), bytes=target.stat().st_size)
    except Exception as e:
        return _err(f"Erro ao criar ZIP: {e}")


def search_files(query, root="", extension=""):
    try:
        base=safe_path(root)
        if not base.is_dir(): return _err(f"A pasta não existe: {base}")
        q=str(query or '').strip().lower()
        ext=str(extension or '').strip().lower()
        if ext and not ext.startswith('.'): ext='.'+ext
        found=[]
        for item in base.rglob('*'):
            if not item.is_file() or item.name.startswith('.'): continue
            if q and q not in item.name.lower(): continue
            if ext and item.suffix.lower()!=ext: continue
            found.append({'nome':item.name,'path':str(item.relative_to(JARVIS_HOME)),'bytes':item.stat().st_size,'ext':item.suffix.lower()})
            if len(found)>=100: break
        return _ok(f"{len(found)} resultado(s)", query=q, itens=found, truncated=len(found)>=100)
    except Exception as e:
        return _err(f"Erro na busca: {e}")

def create_workspace(name):
    try:
        root=safe_path(f"Projetos/{_check_part(str(name or ''))}")
        _protect(root)
        if root.exists(): return _err(f"Workspace já existe: {root.name}")
        for sub in ('Documentos','Arquivos','Exports','Imports','Notas'):
            (root/sub).mkdir(parents=True, exist_ok=False)
        return _ok(f"Workspace '{root.name}' criado", path=str(root), folders=['Documentos','Arquivos','Exports','Imports','Notas'])
    except Exception as e:
        return _err(f"Erro ao criar workspace: {e}")

def document_info(name):
    try:
        target=safe_path(name)
        if not target.is_file(): return _err(f"O arquivo não existe: {target}")
        ext=target.suffix.lower()
        text_ext={'.txt','.md','.csv','.json','.html','.htm','.xml','.rtf'}
        info={'name':target.name,'path':str(target),'extension':ext,'bytes':target.stat().st_size,'kind':'document' if ext in ALLOWED_DOCUMENT_EXT else 'file'}
        if ext in text_ext and target.stat().st_size <= 2_000_000:
            raw=target.read_text(encoding='utf-8',errors='replace')
            info.update({'preview':raw[:MAX_READ],'truncated':len(raw)>MAX_READ})
        return _ok(f"Informações de {target.name}", **info)
    except Exception as e:
        return _err(f"Erro ao inspecionar documento: {e}")

def create_file(name, content=""):
    try:
        target = safe_path(name)
        _protect(target)
        _check_ext(target)
        content = str(content or "")
        if len(content) > MAX_WRITE:
            return _err(f"Conteúdo grande demais (máximo {MAX_WRITE} caracteres).")
        if target.exists():
            return _err(f"O arquivo já existe: {target}")
        if not target.parent.is_dir():
            return _err(f"A pasta de destino não existe: {target.parent}. Crie a pasta primeiro.")
        target.write_text(content, encoding="utf-8")
        return _ok(f"Arquivo criado com sucesso: {target}", path=str(target), created=True)
    except Exception as e:
        return _err(f"Erro ao criar arquivo: {e}")


def append_file(name, content):
    try:
        target = safe_path(name)
        _protect(target)
        _check_ext(target)
        content = str(content or "")
        if len(content) > MAX_WRITE:
            return _err(f"Conteúdo grande demais (máximo {MAX_WRITE} caracteres).")
        if not target.is_file():
            return _err(f"O arquivo não existe: {target}. Crie o arquivo primeiro.")
        with target.open("a", encoding="utf-8") as f:
            f.write(("\n" if target.stat().st_size else "") + content)
        return _ok(f"Texto adicionado em: {target}", path=str(target))
    except Exception as e:
        return _err(f"Erro ao escrever no arquivo: {e}")


def read_file(name):
    try:
        target = safe_path(name)
        if not target.is_file():
            return _err(f"O arquivo não existe: {target}")
        if target.stat().st_size > 2_000_000:
            return _err("Arquivo grande demais para ler (máximo 2 MB).")
        data = target.read_bytes()
        if b"\x00" in data[:2048]:
            return _err("Esse arquivo parece binário (não é texto).")
        text = data.decode("utf-8", errors="replace")
        return _ok(f"Conteúdo de {target.name}", path=str(target), content=text[:MAX_READ],
                   truncated=len(text) > MAX_READ, total_chars=len(text))
    except Exception as e:
        return _err(f"Erro ao ler arquivo: {e}")


def list_files(name=""):
    try:
        target = safe_path(name)
        if not target.is_dir():
            return _err(f"A pasta não existe: {target}")
        items = []
        for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name.startswith("."):
                continue
            items.append({"nome": p.name, "tipo": "pasta" if p.is_dir() else "arquivo",
                          **({"bytes": p.stat().st_size} if p.is_file() else {})})
        return _ok(f"{len(items)} item(ns) em {target}", path=str(target), itens=items[:100],
                   truncated=len(items) > 100)
    except Exception as e:
        return _err(f"Erro ao listar: {e}")


def _dest_for(src, dst_name, into_folder=False):
    dst = safe_path(dst_name)
    if not dst.exists() and (into_folder or (src.is_file() and src.suffix and not dst.suffix)):
        raise ValueError(f"A pasta '{dst.name}' não existe. Crie a pasta primeiro "
                         "(ou informe o nome completo com extensão para copiar/mover com outro nome).")
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        raise ValueError(f"Já existe um item com esse nome no destino: {dst}")
    if not dst.parent.is_dir():
        raise ValueError(f"A pasta de destino não existe: {dst.parent}")
    _check_ext(dst)
    if src.is_dir() and (dst == src or src in dst.parents):
        raise ValueError("Não dá para colocar uma pasta dentro dela mesma.")
    return dst


def move_path(src, dst, into_folder=False):
    try:
        s = safe_path(src)
        _protect(s)
        if not s.exists():
            return _err(f"Não existe: {s}")
        d = _dest_for(s, dst, into_folder)
        shutil.move(str(s), str(d))
        return _ok(f"Movido para: {d}", path=str(d))
    except Exception as e:
        return _err(f"Erro ao mover: {e}")


def copy_path(src, dst, into_folder=False):
    try:
        s = safe_path(src)
        if not s.exists():
            return _err(f"Não existe: {s}")
        d = _dest_for(s, dst, into_folder)
        shutil.copytree(s, d) if s.is_dir() else shutil.copy2(s, d)
        return _ok(f"Copiado para: {d}", path=str(d))
    except Exception as e:
        return _err(f"Erro ao copiar: {e}")


def rename_path(name, new_name):
    try:
        s = safe_path(name)
        _protect(s)
        if not s.exists():
            return _err(f"Não existe: {s}")
        d = s.parent / _check_part(new_name)
        d = d.resolve()
        d.relative_to(JARVIS_HOME.resolve())
        _check_ext(d)
        if d.exists():
            return _err(f"Já existe um item com esse nome: {d}")
        s.rename(d)
        return _ok(f"Renomeado para: {d.name}", path=str(d))
    except Exception as e:
        return _err(f"Erro ao renomear: {e}")


def delete_path(name, confirmed=False):
    """Não apaga de verdade: move para ~/Jarvis/.lixeira (dá para restaurar)."""
    if confirmed is not True:
        return _err("Exclusão exige confirmação do usuário.")
    try:
        s = safe_path(name)
        _protect(s)
        if not s.exists():
            return _err(f"Não existe: {s}")
        TRASH.mkdir(exist_ok=True)
        d = TRASH / f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{s.name}"
        shutil.move(str(s), str(d))
        return _ok(f"'{s.name}' foi para a lixeira do Jarvis: {d}", path=str(d))
    except Exception as e:
        return _err(f"Erro ao apagar: {e}")


# ---------------------------------------------------------------- sistema
def _gb(n):
    return round(n / (1024 ** 3), 1)


def _memory_info():
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return {"ram_total_gb": _gb(st.ullTotalPhys), "ram_livre_gb": _gb(st.ullAvailPhys),
                "ram_em_uso_percent": int(st.dwMemoryLoad)}
    except Exception as e:
        return {"ram_erro": str(e)}


def _disk_info():
    try:
        root = pathlib.Path.home().anchor or "C:\\"
        total, _used, free = shutil.disk_usage(root)
        return {"disco": root, "disco_total_gb": _gb(total), "disco_livre_gb": _gb(free)}
    except Exception as e:
        return {"disco_erro": str(e)}


def _uptime_info():
    try:
        import ctypes
        fn = ctypes.windll.kernel32.GetTickCount64
        fn.restype = ctypes.c_ulonglong
        horas, resto = divmod(int(fn()) // 1000, 3600)
        return {"ligado_ha": f"{horas}h {resto // 60}min"}
    except Exception:
        return {}


def system_info():
    info = {
        "ok": True, "computer": platform.node(), "os": platform.platform(), "system": platform.system(),
        "release": platform.release(), "machine": platform.machine(),
        "processor": os.getenv("PROCESSOR_IDENTIFIER") or platform.processor(),
        "cpu_threads": os.cpu_count(), "python": platform.python_version(),
        "home": str(pathlib.Path.home()), "jarvis_folder": str(JARVIS_HOME.resolve()),
    }
    info.update(_memory_info())
    info.update(_disk_info())
    info.update(_uptime_info())
    return info


def read_log(lines=20):
    try:
        n = max(1, min(int(lines or 20), 100))
        if not LOG_FILE.exists():
            return _ok("Log vazio.", linhas=[])
        return _ok(f"Últimas {n} linhas do log", linhas=LOG_FILE.read_text(encoding="utf-8").splitlines()[-n:])
    except Exception as e:
        return _err(f"Erro ao ler log: {e}")


# ------------------------------------------------------------ rotinas (V12.4)
# As rotinas ficam neste PC (~/Jarvis/.jarvis_agenda.json) e rodam mesmo que o Render esteja dormindo.
AGENDA_FILE = JARVIS_HOME / ".jarvis_agenda.json"
_agenda_lock = threading.RLock()
MAX_ROUTINES = 30
MAX_STEPS = 8
MIN_INTERVAL = 5          # minutos
GRACE_SECONDS = 300       # se o PC estava desligado há mais que isso, a execução é considerada perdida
DAY_NAMES = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
NOT_IN_ROUTINES = {"delete_path", "schedule_add", "schedule_list", "schedule_remove", "schedule_toggle", "read_log"}


def _agenda_load():
    try:
        data = json.loads(AGENDA_FILE.read_text(encoding="utf-8")) if AGENDA_FILE.exists() else []
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _agenda_save(items):
    tmp = AGENDA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(AGENDA_FILE)


def _hm(text):
    h, m = str(text).split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Horário inválido.")
    return h, m


def next_after(when, after):
    """Primeira ocorrência estritamente depois de `after` (None se não houver)."""
    kind = when.get("kind")
    if kind == "once":
        at = datetime.datetime.fromisoformat(when["at"])
        return at if at > after else None
    if kind == "interval":
        return after + timedelta(minutes=int(when["minutes"]))
    h, m = _hm(when["time"])
    if kind == "daily":
        cand = after.replace(hour=h, minute=m, second=0, microsecond=0)
        return cand if cand > after else cand + timedelta(days=1)
    if kind == "weekly":
        days = set(int(d) for d in when["days"])
        for i in range(8):
            cand = (after + timedelta(days=i)).replace(hour=h, minute=m, second=0, microsecond=0)
            if cand > after and cand.weekday() in days:
                return cand
    return None


def describe_when(when):
    kind = when.get("kind")
    if kind == "daily":
        return f"todo dia às {when['time']}"
    if kind == "weekly":
        return f"{', '.join(DAY_NAMES[int(d)] for d in sorted(when['days']))} às {when['time']}"
    if kind == "interval":
        mi = int(when["minutes"])
        return f"a cada {mi // 60} h" if mi % 60 == 0 else f"a cada {mi} min"
    if kind == "once":
        return f"uma vez em {datetime.datetime.fromisoformat(when['at']):%d/%m %H:%M}"
    return "?"


def _normalize_when(when, now):
    if not isinstance(when, dict):
        raise ValueError("Horário da rotina ausente.")
    kind = when.get("kind")
    if kind == "once" and "in_minutes" in when:
        mins = int(when["in_minutes"])
        if not 1 <= mins <= 10080:
            raise ValueError("Use de 1 minuto até 7 dias.")
        return {"kind": "once", "at": (now + timedelta(minutes=mins)).isoformat(timespec="seconds")}
    if kind == "once":
        h, m = _hm(when.get("time"))
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        day = when.get("day", "auto")
        if day == "tomorrow":
            cand += timedelta(days=1)
        elif cand <= now:
            if day == "today":
                raise ValueError(f"Hoje às {h:02d}:{m:02d} já passou. Diga 'amanhã' ou outro horário.")
            cand += timedelta(days=1)
        return {"kind": "once", "at": cand.isoformat(timespec="seconds")}
    if kind == "interval":
        mins = int(when.get("minutes", 0))
        if not MIN_INTERVAL <= mins <= 1440:
            raise ValueError(f"O intervalo deve ficar entre {MIN_INTERVAL} minutos e 24 horas.")
        return {"kind": "interval", "minutes": mins}
    if kind == "daily":
        _hm(when.get("time"))
        return {"kind": "daily", "time": when["time"]}
    if kind == "weekly":
        _hm(when.get("time"))
        days = sorted({int(d) for d in when.get("days", []) if 0 <= int(d) <= 6})
        if not days:
            raise ValueError("Nenhum dia da semana informado.")
        return {"kind": "weekly", "days": days, "time": when["time"]}
    raise ValueError("Tipo de rotina desconhecido.")


def _validate_steps(steps):
    if not isinstance(steps, list) or not steps:
        raise ValueError("A rotina precisa de pelo menos um passo.")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"Máximo de {MAX_STEPS} passos por rotina.")
    clean = []
    for st in steps:
        action = st.get("action") if isinstance(st, dict) else None
        if action not in ACTIONS or action in NOT_IN_ROUTINES:
            raise ValueError(f"Ação não permitida em rotinas: {action}")
        params = st.get("params") if isinstance(st.get("params"), dict) else {}
        clean.append({"action": action, "params": params})
    return clean


def schedule_add(when, steps, resumo=""):
    try:
        now = datetime.datetime.now()
        spec = _normalize_when(when, now)
        steps = _validate_steps(steps)
        with _agenda_lock:
            items = _agenda_load()
            if len(items) >= MAX_ROUTINES:
                return _err(f"Limite de {MAX_ROUTINES} rotinas. Remova alguma antes.")
            nxt = next_after(spec, now)
            if nxt is None:
                return _err("Esse horário já passou.")
            rid = max([int(i.get("id", 0)) for i in items] or [0]) + 1
            items.append({"id": rid, "when": spec, "steps": steps, "resumo": str(resumo or "")[:200],
                          "enabled": True, "next_run": nxt.isoformat(timespec="seconds"), "last_run": None,
                          "last_ok": None, "last_msg": "", "runs": 0, "created": now.isoformat(timespec="seconds")})
            _agenda_save(items)
        return _ok(f"Rotina #{rid} criada: {describe_when(spec)}. Próxima execução: {nxt:%d/%m %H:%M}.",
                   id=rid, quando=describe_when(spec), proxima=f"{nxt:%d/%m %H:%M}")
    except Exception as e:
        return _err(f"Não consegui criar a rotina: {e}")


def schedule_list():
    with _agenda_lock:
        items = _agenda_load()
    rows = []
    for r in items:
        nr = r.get("next_run")
        lr = r.get("last_run")
        rows.append({
            "id": r.get("id"), "quando": describe_when(r.get("when", {})), "o_que_faz": r.get("resumo", ""),
            "ativa": bool(r.get("enabled")),
            "proxima": datetime.datetime.fromisoformat(nr).strftime("%d/%m %H:%M") if nr else "-",
            "ultima_execucao": datetime.datetime.fromisoformat(lr).strftime("%d/%m %H:%M") if lr else "-",
            "ultimo_resultado": ("ok" if r.get("last_ok") else r.get("last_msg") or "erro") if lr or r.get("last_msg") else "-",
            "execucoes": r.get("runs", 0),
        })
    return _ok(f"{len(rows)} rotina(s)", rotinas=rows)


def schedule_remove(rid):
    try:
        rid = int(rid)
        with _agenda_lock:
            items = _agenda_load()
            keep = [i for i in items if int(i.get("id", 0)) != rid]
            if len(keep) == len(items):
                return _err(f"Não existe a rotina #{rid}.")
            _agenda_save(keep)
        return _ok(f"Rotina #{rid} removida.")
    except Exception as e:
        return _err(f"Erro ao remover rotina: {e}")


def schedule_toggle(rid, enabled):
    try:
        rid = int(rid)
        with _agenda_lock:
            items = _agenda_load()
            for r in items:
                if int(r.get("id", 0)) == rid:
                    if enabled:
                        nxt = next_after(r["when"], datetime.datetime.now())
                        if nxt is None:
                            return _err(f"A rotina #{rid} era de uma vez só e já passou. Crie outra.")
                        r["next_run"] = nxt.isoformat(timespec="seconds")
                    r["enabled"] = bool(enabled)
                    _agenda_save(items)
                    return _ok(f"Rotina #{rid} {'ativada' if enabled else 'pausada'}.")
        return _err(f"Não existe a rotina #{rid}.")
    except Exception as e:
        return _err(f"Erro ao alterar rotina: {e}")


def _advance(r, now):
    nxt = next_after(r["when"], now)
    if r["when"].get("kind") == "once" or nxt is None:
        r["enabled"], r["next_run"] = False, None
    else:
        r["next_run"] = nxt.isoformat(timespec="seconds")


def scheduler_tick(now=None):
    """Executa as rotinas vencidas. Chamado a cada segundo por uma thread."""
    now = now or datetime.datetime.now()
    with _agenda_lock:
        items = _agenda_load()
        changed = False
        for r in items:
            if not r.get("enabled") or not r.get("next_run"):
                continue
            due = datetime.datetime.fromisoformat(r["next_run"])
            if due > now:
                continue
            changed = True
            if (now - due).total_seconds() > GRACE_SECONDS:
                r["last_ok"], r["last_msg"] = False, f"perdida: o agente estava desligado às {due:%d/%m %H:%M}"
                print(f"[ROTINA #{r['id']}] pulada ({r['last_msg']})")
                _advance(r, now)
                continue
            ok, msg = True, ""
            for step in r.get("steps", []):
                res = execute_action(step["action"], step.get("params"))
                if not res.get("ok"):
                    ok, msg = False, res.get("error", "erro")
                    break
            r["last_run"], r["last_ok"], r["last_msg"] = now.isoformat(timespec="seconds"), ok, msg
            r["runs"] = int(r.get("runs", 0)) + 1
            print(f"[ROTINA #{r['id']}] {'OK' if ok else 'ERRO: ' + msg} - {r.get('resumo', '')}"[:200])
            _advance(r, now)
        if changed:
            _agenda_save(items)


def scheduler_loop():
    while True:
        try:
            scheduler_tick()
        except Exception as e:
            print(f"[ROTINAS] erro: {e}")
        time.sleep(1)


# ------------------------------------------------------------ batimento (dashboard)
_cpu_prev = None


def _cpu_percent():
    """Uso de CPU (%) desde a última medição. None na 1ª vez ou fora do Windows."""
    global _cpu_prev
    try:
        import ctypes

        class FT(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

        i, k, u = FT(), FT(), FT()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u)):
            return None
        val = lambda f: (f.hi << 32) | f.lo
        idle, total = val(i), val(k) + val(u)      # no Windows, "kernel" já inclui o tempo ocioso
        prev, _cpu_prev = _cpu_prev, (idle, total)
        if not prev or total - prev[1] <= 0:
            return None
        return round(100 * (1 - (idle - prev[0]) / (total - prev[1])), 1)
    except Exception:
        return None


def build_heartbeat():
    hb = {
        "device_id": CONFIG.get("device_id"),
        "version": VERSION,
        "computer": platform.node(),
        "capabilities": ["computer", "filesystem", "browser", "scheduler", "app_control", "app_inventory", "file_manager", "document_center", "import_export", "zip"],
        "cpu_percent": _cpu_percent(),
          "jarvis_folder": str(JARVIS_HOME.resolve())}
    for part in (_memory_info(), _disk_info(), _uptime_info()):
        hb.update({k: v for k, v in part.items() if not k.endswith("_erro") and k != "disco"})
    try:
        with _agenda_lock:
            ativas = [r for r in _agenda_load() if r.get("enabled") and r.get("next_run")]
        hb["rotinas_ativas"] = len(ativas)
        if ativas:
            nxt = min(ativas, key=lambda r: r["next_run"])
            hb["proxima_rotina"] = {"quando": datetime.datetime.fromisoformat(nxt["next_run"]).strftime("%d/%m %H:%M"),
                                    "resumo": nxt.get("resumo", "")}
    except Exception:
        pass
    return hb


def heartbeat_loop():
    while True:
        try:
            requests.post(f"{CONFIG['gateway_url']}/agent/heartbeat", json=build_heartbeat(),
                          headers=headers(), timeout=10)
        except Exception:
            pass          # sem barulho: o poll principal já avisa se o gateway cair
        time.sleep(10)


# --------------------------------------------------------------- despacho
ACTIONS = {
    "open_app": lambda p: open_app(p.get("app")),
    "list_apps": lambda p: list_apps(),
    "open_folder": lambda p: open_folder(p.get("name", ""), p.get("app")),
    "open_file": lambda p: open_file(p.get("name"), p.get("app")),
    "open_url": lambda p: open_url(p.get("url")),
    "search_web": lambda p: search_web(p.get("query"), p.get("engine", "google")),
    "create_folder": lambda p: create_folder(p.get("name")),
    "create_file": lambda p: create_file(p.get("name"), p.get("content", "")),
    "append_file": lambda p: append_file(p.get("name"), p.get("content", "")),
    "read_file": lambda p: read_file(p.get("name")),
    "list_files": lambda p: list_files(p.get("name", "")),
    "move_path": lambda p: move_path(p.get("src"), p.get("dst"), p.get("into_folder", False)),
    "copy_path": lambda p: copy_path(p.get("src"), p.get("dst"), p.get("into_folder", False)),
    "rename_path": lambda p: rename_path(p.get("name"), p.get("new_name")),
    "delete_path": lambda p: delete_path(p.get("name"), p.get("confirmed")),
    "upload_file": lambda p: upload_file(p.get("name"), p.get("data_b64"), p.get("overwrite", False)),
    "download_file": lambda p: download_file(p.get("name")),
    "create_zip": lambda p: create_zip(p.get("src"), p.get("dst")),
    "document_info": lambda p: document_info(p.get("name")),
    "search_files": lambda p: search_files(p.get("query", ""), p.get("root", ""), p.get("extension", "")),
    "create_workspace": lambda p: create_workspace(p.get("name")),
    "system_info": lambda p: system_info(),
    "read_log": lambda p: read_log(p.get("lines", 20)),
    "schedule_add": lambda p: schedule_add(p.get("when"), p.get("steps"), p.get("resumo", "")),
    "schedule_list": lambda p: schedule_list(),
    "schedule_remove": lambda p: schedule_remove(p.get("id")),
    "schedule_toggle": lambda p: schedule_toggle(p.get("id"), p.get("enabled", True)),
}
ALLOWED_ACTIONS = set(ACTIONS)


def log_action(action, params, result):
    try:
        safe = {k: (f"<{len(str(v))} caracteres>" if k == "content" else v) for k, v in (params or {}).items()}
        line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {action} | {safe} | {'OK' if result.get('ok') else 'ERRO'}"
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def execute_action(action, params):
    if action not in ACTIONS:
        return _err(f"Ação não permitida: {action}")
    params = params if isinstance(params, dict) else {}
    try:
        result = ACTIONS[action](params)
    except Exception as e:
        result = _err(f"Erro inesperado: {e}")
    if action not in ("read_log", "schedule_list"):
        log_action(action, params, result)
    return result


def send_result(command_id, action, result):
    r = requests.post(f"{CONFIG['gateway_url']}/agent/results",
                      json={"command_id": command_id, "action": action, "result": result},
                      headers=headers(), timeout=15)
    r.raise_for_status()


def main():
    print("=" * 56)
    print(f" JARVIS LOCAL AGENT V{VERSION}")
    print("=" * 56)
    first_run_setup(CONFIG)
    if not CONFIG["gateway_url"] or not CONFIG["token"]:
        input("Configuração incompleta. Pressione ENTER para fechar...")
        return
    print(f"[INFO] Gateway: {CONFIG['gateway_url']}")
    print(f"[INFO] Pasta segura: {JARVIS_HOME}")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    n_rot = sum(1 for r in _agenda_load() if r.get("enabled"))
    print(f"[INFO] Rotinas ativas: {n_rot}")
    print("[OK] Aguardando comandos... (Ctrl+C para sair)\n")

    session = requests.Session()
    last_error = ""
    while True:
        try:
            r = session.get(f"{CONFIG['gateway_url']}/agent/poll", headers=headers(), timeout=20)
            if r.status_code == 401:
                print("[ERRO] Token recusado pelo Gateway. Confira o LOCAL_AGENT_TOKEN.")
                time.sleep(10)
                continue
            r.raise_for_status()
            last_error = ""
            for cmd in r.json().get("commands", []):
                cid = cmd.get("command_id") or cmd.get("id")
                action = cmd.get("action") or "unknown"
                if not cid:
                    continue
                result = execute_action(action, cmd.get("params"))
                trace_id = cmd.get("trace_id")
                if trace_id and isinstance(result, dict):
                    result["trace_id"] = trace_id  # V19: devolve o trace ID ao Gateway/Command OS
                status = "OK  " if result.get("ok") else "ERRO"
                tr = f" (trace {str(trace_id)[:8]})" if trace_id else ""
                print(f"[{status}] {action}{tr}: {result.get('message') or result.get('error') or ''}"[:200])
                try:
                    send_result(cid, action, result)
                except Exception as e:
                    print(f"[ERRO] Não consegui enviar o resultado: {e}")
        except requests.RequestException as e:
            if str(e) != last_error:  # não repete a mesma mensagem a cada ciclo
                print(f"[GATEWAY] Conexão indisponível: {e}")
                last_error = str(e)
        except KeyboardInterrupt:
            print("\n[INFO] Agente encerrado.")
            break
        except Exception as e:
            print(f"[ERRO] {e}")
        time.sleep(CONFIG["poll_seconds"])


if __name__ == "__main__":
    main()
