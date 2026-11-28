# Changelog

## Unreleased（仓库工具，不影响 Skill）

新增 `tools/blindtest/`：同位点按切换盲测工具（对齐画框、每批含两道同图哨兵、答案表与页面分离、自动计分并判定合并门槛：无倒退且净胜）。测试照片放在本地 `blindtest_data/`，不进仓库。Skill 本身没有改动。

Added `tools/blindtest/`: same-position tap-to-toggle blind tests (frame alignment, two identical-image sentinels per batch, answer key kept out of the page, automatic scoring with the merge gate: no regression and a net win). Test photos stay in a local `blindtest_data/` folder and are never committed. The Skill itself is unchanged.

## v1.6.4

只更新构图判断的三处文字：近景画框不算杂物，保留主体运动方向的空间和平衡画面的留白，强竖线与画框留出空隙。其余与 v1.6.3 相同。

脚本未改动，回执中的版本标记仍显示 v1.6.3，属正常。

Only three composition guidelines changed: keep foreground framing, preserve space for subject movement and visual balance, and leave room between strong vertical lines and the frame edge. Everything else is the same as in v1.6.3.

The scripts are unchanged, so the version shown in receipts is still v1.6.3. This is expected.
