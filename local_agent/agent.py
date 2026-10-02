"""JARVIS LOCAL AGENT V11.9

Roda no seu Windows como usuário normal. Busca comandos no Gateway, executa
apenas ações permitidas dentro de ~/Jarvis e devolve o resultado real.
Não existe shell remoto: cada ação é uma função fixa abaixo.
"""
import datetime
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from urllib.parse import quote_plus, urlparse

import requests

VERSION = "11.9"
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
    cfg = {"gateway_url": "", "token": "", "poll_seconds": 1}
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
        cfg["poll_seconds"] = max(0.5, float(cfg.get("poll_seconds", 1)))
    except Exception:
        cfg["poll_seconds"] = 1
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
        json.dumps({"gateway_url": url, "token": token, "poll_seconds": cfg["poll_seconds"]}, indent=2),
        encoding="utf-8",
    )
    print("\n[OK] Configuração salva em config.json\n")
    return cfg


CONFIG = load_config()


def headers():
    return {"X-Agent-Token": CONFIG["token"], "Content-Type": "application/json"}


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


APPS = {
    "notepad": ("popen", ["notepad.exe"]),
    "calculator": ("popen", ["calc.exe"]),
    "paint": ("popen", ["mspaint.exe"]),
    "taskmgr": ("popen", ["taskmgr.exe"]),
    "word": ("startfile", "winword"),
    "excel": ("startfile", "excel"),
    "powerpoint": ("startfile", "powerpnt"),
}


def open_app(app):
    app = str(app or "").lower().strip()
    try:
        if app == "vscode":
            exe = _find_vscode()
            if not exe:
                return _err("VS Code não encontrado. Verifique se está instalado.")
            subprocess.Popen([exe])
        elif app == "browser":
            webbrowser.open("https://www.google.com")
        elif app == "explorer":
            _startfile(JARVIS_HOME)
        elif app in APPS:
            kind, target = APPS[app]
            if kind == "popen":
                subprocess.Popen(target, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                _startfile(target)
        else:
            return _err(f"Aplicativo não permitido: {app}. Permitidos: vscode, browser, explorer, "
                        + ", ".join(sorted(APPS)))
        return _ok(f"Aplicativo '{app}' aberto.")
    except FileNotFoundError:
        return _err(f"O aplicativo '{app}' não foi encontrado neste computador.")
    except Exception as e:
        return _err(f"Erro ao abrir '{app}': {e}")


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


# --------------------------------------------------------------- despacho
ACTIONS = {
    "open_app": lambda p: open_app(p.get("app")),
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
    "system_info": lambda p: system_info(),
    "read_log": lambda p: read_log(p.get("lines", 20)),
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
    if action != "read_log":
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
                status = "OK  " if result.get("ok") else "ERRO"
                print(f"[{status}] {action}: {result.get('message') or result.get('error') or ''}"[:200])
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
