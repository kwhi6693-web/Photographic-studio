# Real G outputs

From the owner's runs of Photographic Studio in an LLM agent with image generation, 2026-11-13. Per case: `original.*`
(the bytes the agent received), `g.png` (the G intermediate as the image tool returned it), `params.json` (the
director's grade parameters), `receipt.json` (the agent's finish.py receipt).

- `b1_*`, run under v1.0.1: 01 garden in backlight, 02 bronze sword (museum), 03 study window, 04 screen and narrow
  window, 05 lake framed by branches.
- `c1_05`, run under v1.2.5 (2026-11-19): boat on a garden canal; `g.png` is the agent's second G. Delivered then as N
  direct because G dimmed the sky gaps and their reflections; kept on the G route since the v1.2.5 light repair.
- `b2_*`, run under v1.0.3: 01 lit painted screen, 02 glass orchid frames, 03 glass sunflowers (`g.png` is the agent's second G, the one finish.py used), 04 pale violet glass vase in coloured-glass frames, 05 blue-glazed vase, 06 jade suit with
  visitors, 07 bronze ox lamp, 08 celadon jar and lit screen, 09 lacquer seat and brocade, 10 eaves and plaque by day.

Do not change these files; add new cases as new folders and give each an expected route in `test_real_g.py`.
