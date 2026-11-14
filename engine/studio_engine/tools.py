"""Thin wrappers around the deterministic tools in photographic-studio/optional (they stay the single source of truth)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class ToolError(RuntimeError):
    pass


class Tools:
    def __init__(self, tools_dir: Path, timeout_s: int = 900):
        self.dir = Path(tools_dir)
        self.timeout = timeout_s
        if not (self.dir / 'finish.py').exists():
            raise ToolError(f'tools not found in {self.dir}')

    def run(self, tool: str, *args, expect_json: bool = True) -> dict:
        cmd = [sys.executable, '-I', '-B', str(self.dir / tool), *map(str, args)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        if not expect_json:
            return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr[-2000:]}
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            raise ToolError(f'{tool} failed ({p.returncode}): {p.stderr[-800:] or p.stdout[-800:]}')

    def measure(self, img):
        return self.run('measure.py', img)

    def check_g(self, src, g):
        return self.run('check_g_output.py', src, g)

    def finish(self, src, g, params_json, out, receipt, museum=False):
        r = self.run('finish.py', src, g, params_json, out, receipt, *(['--genre=museum'] if museum else []))
        if not Path(out).exists():
            raise ToolError(f'finish.py produced no image: {str(r)[:400]}')
        return json.loads(Path(receipt).read_text(encoding='utf-8')) if Path(receipt).exists() else r

    def settle(self, src, img, out, receipt, museum=False, n_direct=False):
        return self.run('settle.py', src, img, out, receipt,
                        *(['--genre=museum'] if museum else []), *(['--n-direct'] if n_direct else []))

    def n_trim(self, img, out, receipt):
        return self.run('n_trim.py', img, out, receipt)

    def intensity(self, src, img, museum=False):
        return self.run('intensity_check.py', src, img, *(['--genre=museum'] if museum else []))

    def physics(self, src, img):
        return self.run('physics_check.py', src, img)
