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
| `test_real.py` | The same questions on the owner's six real photos (`fixtures/real/`); every defect tested there was first judged by eye |

## Known gaps

Shown as `xfail` in the test output. They are recorded, not fixed: changing a threshold must be shown not to make
any other photo worse, and these tests are the means to show that.

**On real photos** (each seen by eye before it was written down):

| Photo | Defect | What happens |
|---|---|---|
| sunflower case, night tower | G invents a glow on the dark background | `finish.py` delivers about 5–7 L* of it; on the night tower the receipt says `DELIVER` with no flag |
| orchid panels | glowing oval on the dark wall | `physics_check.py` passes it (`finish.py` still removes it, by falling back to N direct) |
| clock tower, arcade, glass lotus | white or crunchy rims along strong edges | `physics_check.py` passes them. The halo measure looks at a glow on the dark side and a dark rim on the bright side; these rims brighten the bright side, which may be why |

**On synthetic scenes only:**

| Scene | Defect | Note |
|---|---|---|
| museum | ring of light around the exhibit | caught on all six real photos: the synthetic exhibit is unlike real ones |
| museum | exhibit highlights pressed down | `intensity_check.py` objects |
| day | shade warmer than the sunlit wall | not tested on real photos (needs a mask of the shade) |
| night | whole frame lifted flat | caught on the real night photo |

What did not go wrong: on all six real photos, an unchanged photo and an honest global edit were never accused;
a texture-wiped G still gave a final with the original's detail; the same input gave byte-identical output.

## 中文

这里的测试不依赖任何人的说法。合成场景的光线由构造决定，缺陷逐条对应 `references/physics.md` 的规则；工具原样运行，不做修改。
测试放在安装包之外，安装包和哈希清单不变。`fixtures/real/` 是仓库所有者的六张真实照片。输出里的 `xfail` 是已记录、尚未修的漏报（见上表），真实照片上的每一条都先用眼睛确认过。
