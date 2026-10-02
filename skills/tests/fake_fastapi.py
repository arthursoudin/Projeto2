"""Shim mínimo de fastapi, só para testar as rotas do gateway sem instalar nada."""
import sys, types

class HTTPException(Exception):
    def __init__(self, status_code, detail=''):
        self.status_code, self.detail = status_code, detail

class FastAPI:
    def __init__(self, **kw): self.routes = {}
    def _reg(self, method):
        def deco(path):
            def wrap(fn): self.routes[(method, path)] = fn; return fn
            return wrap
        return deco
    def get(self, path): return self._reg('GET')(path)
    def post(self, path): return self._reg('POST')(path)

class Request: pass
class BackgroundTasks:
    def __init__(self): self.tasks = []
    def add_task(self, fn, *a, **k): self.tasks.append((fn, a, k))
def Header(default=None): return default
class PlainTextResponse:
    def __init__(self, content): self.body = content

def install():
    fa = types.ModuleType('fastapi')
    fa.FastAPI, fa.Request, fa.Header, fa.HTTPException, fa.BackgroundTasks = FastAPI, Request, Header, HTTPException, BackgroundTasks
    fr = types.ModuleType('fastapi.responses'); fr.PlainTextResponse = PlainTextResponse
    sys.modules['fastapi'], sys.modules['fastapi.responses'] = fa, fr
