import ast, pathlib, zipfile

ROOT=pathlib.Path(__file__).resolve().parent

def test_v14_5_sources_compile():
    for p in [ROOT/"app.py", ROOT/"gateway.py", ROOT/"security.py", ROOT/"local_agent"/"agent.py"]:
        ast.parse(p.read_text(encoding="utf-8"))

def test_v14_5_file_actions_present():
    s=(ROOT/"local_agent"/"agent.py").read_text(encoding="utf-8")
    for name in ["upload_file", "download_file", "create_zip", "document_info", "search_files", "create_workspace"]:
        assert name in s

def test_v14_5_gateway_actions():
    s=(ROOT/"gateway.py").read_text(encoding="utf-8")
    for name in ["upload_file", "download_file", "create_zip", "document_info", "search_files", "create_workspace"]:
        assert name in s
