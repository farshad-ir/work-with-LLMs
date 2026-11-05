import py_compile
path = "C:/Users/Rezvan/work/codex/work-with-LLMs/app/model_rotation.py"
mt5_path = "C:/Users/Rezvan/work/codex/work-with-LLMs/mt5_rotation.py"

# Load main rotation content
content = open(path, encoding="utf-8").read()
# Load MT5 rotation code and strip leading BOM if any
mt5 = open(mt5_path, encoding="utf-8").read()
if mt5.startswith("\ufeff"):
    mt5 = mt5[1:]

marker = "def get_rotation_status()"
pos = content.find(marker)
if pos >= 0:
    content = content[:pos] + mt5 + "\n\n" + content[pos:]
    open(path, "w", encoding="utf-8").write(content)
    try:
        py_compile.compile(path, doraise=True)
        print("Patched and syntax OK")
    except py_compile.PyCompileError as e:
        print("Syntax error", e)
else:
    print("marker missing")
