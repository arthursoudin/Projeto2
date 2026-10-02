import ast, pathlib, zipfile
ROOT=pathlib.Path(__file__).parent
for p in [ROOT/"app.py",ROOT/"gateway.py",ROOT/"devices.py",ROOT/"orchestrator.py",ROOT/"pc_control.py",ROOT/"local_agent"/"agent.py"]:
    ast.parse(p.read_text(encoding="utf-8"))
text=(ROOT/"local_agent"/"agent.py").read_text(encoding="utf-8")
assert "list_apps" in text and "app_control" in text
text2=(ROOT/"gateway.py").read_text(encoding="utf-8")
assert "devices/apps" in text2 and "list_apps" in text2
print("V14.0 OK")
