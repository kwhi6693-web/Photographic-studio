"""selfcheck.py must ask only for libraries a tool imports, or hosts install packages nobody uses (2026-11-13: the agent
installed scikit-image because the self check listed it)."""
import ast, json
from conftest import TOOLS, run_tool


def imported_top_modules():
    mods = set()
    for p in TOOLS.glob('*.py'):
        if p.name == 'selfcheck.py': continue
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import): mods |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0: mods.add(node.module.split('.')[0])
    return mods


def test_selfcheck_lists_only_libraries_the_tools_import():
    listed = set(json.loads(run_tool('selfcheck.py').stdout)['modules'])
    assert listed <= imported_top_modules(), listed - imported_top_modules()
    assert {'numpy', 'PIL', 'cv2'} <= listed
