# Tests

Evidence that does not depend on anyone's word. Run `pip install -r tests/requirements.txt && python -m pytest tests -rx`.

The tests live outside `photographic-studio/`, so the installable package and its `SHA256SUMS.txt` are unchanged.
The tools are run unmodified, each as its own process, the way an agent runs them.

| File | What it proves |
|---|---|
| `synth.py` | Scenes built from fixed seeds (day, museum, night) whose light is known by construction, and defects that each break one rule of `references/physics.md` |
| `test_manifest.py` | The package is exactly what `SHA256SUMS.txt` lists |
| `test_tools.py` | Every tool starts; grading is deterministic and keeps to its limits |
| `test_pipeline.py` | The default route's promises: same input gives the same output, the final keeps the original's size and fine detail, light G invented is mostly blocked, light G removed is put back, a wrong scene is refused, an invisible edit is never a clean pass |
| `test_checkers.py` | Which defects `physics_check.py` reports, and that it does not accuse an honest edit |

## Known gaps

Shown as `xfail` in the test output. Each is a defect a checker lets through on a synthetic scene. They are recorded,
not fixed: the thresholds were tuned on real photos, so changing them needs real originals to show nothing gets worse.

| Scene | Defect | What happens |
|---|---|---|
| museum | ring of light around the exhibit | `physics_check.py` passes it |
| museum | exhibit highlights pressed down | `physics_check.py` passes it; `intensity_check.py` objects |
| day | shade turned warmer than the sunlit wall | `physics_check.py` passes it |
| night | whole frame lifted flat | `physics_check.py` passes it; `intensity_check.py` objects |
| night, museum | G invents a glow on a black background | `finish.py` removes about three quarters; about 5.5 L* remains, and the receipt does not mention it |

Synthetic scenes are not photographs. A gap here says where to look on real photos; it does not say a real photo failed.

## 中文

这里的测试不依赖任何人的说法。合成场景的光线由构造决定，缺陷逐条对应 `references/physics.md` 的规则；工具原样运行，不做修改。
测试放在安装包之外，安装包和哈希清单不变。输出里的 `xfail` 是已记录、尚未修的检查器漏报（见上表）；合成场景不是照片，漏报只说明该去真实照片上查哪里。
