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
| `test_real.py` | The same questions on the owner's ten real photos (`fixtures/real/`), including the originals of all six taste samples; every defect tested there was first judged by eye. It also feeds the six approved finals in as G and requires that the glow check stays quiet on them |

## Known gaps

Shown as `xfail` in the test output. They are recorded, not fixed: changing a threshold must be shown not to make
any other photo worse, and these tests are the means to show that.

**On real photos** (each seen by eye before it was written down):

| Photo | Defect | What happens |
|---|---|---|
| orchid panels | glowing oval on a mid-dark wall (L* 35) | `physics_check.py` passes it; the wall is lighter than what counts as a dark background, so `finish.py` removes it only by falling back to N direct. Widening that needs real G outputs |

**Fixed in v1.0.2:** edge halos on all ten photos (the old measure averaged over the whole frame at fixed pixel
distances; a regional edge-gain measure now flags them, while `grade.py` clarity 0.6 and the museum level-3 grade pass);
shade turned warmer than the light (the sky was counted as "lit"). G's invented glow on a dark background used to reach the final (4–9 L* above its surroundings on
sunflowers, night tower, glass lotus, blue vase; once with a clean `DELIVER`). Now 0.8–1.8, with G's look kept.
`test_real.py` also guards the six approved finals: fed in as G, the glow handling must leave them alone.

**On synthetic scenes only:**

| Scene | Defect | Note |
|---|---|---|
| museum | ring of light around the exhibit | caught on all ten real photos: the synthetic exhibit is unlike real ones |
| museum | exhibit highlights pressed down | not separable from `grade.py`'s own highlight recovery; `look_transfer.py` puts back light G removed |

What did not go wrong: on all ten real photos, an unchanged photo and an honest global edit were never accused;
a texture-wiped G still gave a final with the original's detail; the same input gave byte-identical output.

## 中文

这里的测试不依赖任何人的说法。合成场景的光线由构造决定，缺陷逐条对应 `references/physics.md` 的规则；工具原样运行，不做修改。
测试放在安装包之外，安装包和哈希清单不变。`fixtures/real/` 是仓库所有者的六张真实照片。输出里的 `xfail` 是已记录、尚未修的漏报（见上表），真实照片上的每一条都先用眼睛确认过。
