---
name: photographic-studio
description: 独立的非人像摄影后期工作流，面向任何能看图的 agent。用户发来一张或多张照片并要求修图（例如“修”“修一下这张”“修成成片”）时使用，适用于建筑、街景、风光、园林、夜景、室内、静物、展品等非人像照片。大模型读片、写导演单、定构图，宿主的图像编辑工具出片，确定性工具贴回关键细节、裁切、保护高光、拦下硬故障，直接交付一张成片；按宿主实际具备的工具分级执行。
---

# Photographic Studio v1.5.0

用户发来照片、说一句“修”，就得到一张成片：**有明显的摄影表现力、仍然像原片、符合真实的光、看不出 AI 痕迹**。表现力第一，其余三条同时成立。

分工：**大模型管审美**（导演单、构图、框位、看硬伤）；**代码管硬活**（对齐、贴回、裁切、高光保护、硬故障兜底）。本文件是唯一的执行说明，按顺序做即可；参考文件只在需要细节时查。

## 1. 边界

- 只做非人像。偶然入镜的人物保持原样：不美化、不塑形、不推断身份。主体是人像时不修，一句话说明。
- 用户发来照片并要求修图，即视为对这张照片的当次编辑授权。只要求分析时不编辑。
- 照片不留作风格库或训练素材；不外发到第三方服务。用户有最终接受权。

## 2. 开始前（每条对话一次）

运行 `optional/selfcheck.py`，再确认自己有没有图像编辑工具（下称 G）。定级：**T1** 有 G 且能跑代码（走第 3 节）；**T2** 只能跑代码（第 4 节快速 N 直出）；**T3** 只有 G（第 3 节只做 1、3 步，交付 G 稿并注明“未做确定性检查”）；**T4** 都没有（一句话说明做不了）。

## 3. “修”（T1 主线，多张照片逐张做）

**第 1 步 读片，写进参数文件和一行记录**

1. **看点与导演单**：一句“看点｜风格”（看点不只是叙事，还有几何、光影、色彩、质感、氛围），再写 **2–4 个具体的提升动作**，每个说清对谁、往哪个方向，例如：
   - 光：让现有的侧光聚到主体上，四周和前景稍暗下去；
   - 分离：主体与背景拉开明暗或冷暖；
   - 色彩：理顺主色、压住抢眼的杂色、受光面暖、阴影偏冷；
   - 纵深与氛围：远景更通透或更有雾感，天空从上往下自然加深。
   只写方向，不写数字。动作要让成片在正常尺寸下一眼看得出比原片好。
2. **keep（要保护的局部）**：画面里所有看得到的文字和招牌（包括小招牌、价签、贴纸）、近景和中景里清晰的人、展品主体，一律 `{"what": …, "box": [x0, y0, x1, y1], "mode": "content"}`（0–1 的比例坐标）。**框要紧贴对象**，不要把大片天空、墙面框进去（贴回的是原片像素，框越大越容易看出补丁）。没有就写“无需保护”。博物馆展品必须有 keep。
3. **构图（每张都要判断）**：按专业摄影师的眼光，写一行“看点 → 用到的一两种手法 → 裁或不裁、为什么”。不写理由的“不动”不算判断。
   - 手法：围绕看点取景；三分法或对称；引导线从边角进入、指向主体；给主体留白和呼吸；清掉边角的亮斑、半截杂物；地平线和建筑竖线拉直（`rotate`），竖线汇聚明显时做透视矫正（`persp`）；按主体选比例（高耸用竖幅、展开用横幅、集中用方形）。
   - 必查：不在门窗、柱子的中段或人物关节上下刀；可读的文字、主体、人物要么完整，要么整体裁掉；地平线不压在正中（对称倒影除外）。
   - 底线：只裁不扩；裁切后至少保留原画面的 75%，长边不少于 1000 像素（超过的话工具会不裁直接交付）。框景、对角线本身就是看点时，不裁也是好答案。
   - 写成 `"reframe": {"box": [l, t, r, b], "allow_aspect_change": true}`，或 `rotate`、`persp`（`references/reframe_rules.md`）。
   - 原片有以下任一情况时，不准直接写“不动”：①地平线或竖线明显歪（先 `rotate` 拉直）；②边角有杂物、碎枝、半截东西；③大片空天或空地；④主体偏小、画面发散。这时必须先用 `reframe.py` 裁出 1 张候选，和原图并排看一眼：更好就用，不比原图好就不裁，并写一句为什么。

**第 2 步 核对框位（有 keep 时必做）**

运行 `python3 optional/keep_preview.py 原片 参数.json 框位预览.png`，**看这张预览图**：每个编号框是否真的盖住了它写的东西（白线每格 0.1）。偏了就改坐标再画，直到全部盖准。坐标是估出来的，工具判断不了框里该是什么，只有这一眼能发现。

**第 3 步 调用 G**

- **一次只把这一张原片交给 G**，一条消息里有多张照片也一样。原片要在最近一条用户消息里。
- 提示词：
  ```
  Edit the provided photo into a finished, professional-grade photograph with strong but natural photographic impact.
  Output exactly one photo with the same framing, viewpoint and layout as this single input photo. Not a grid, collage, contact sheet or side-by-side.
  Make the light and colour work: <第 1 步的 2–4 个提升动作，用英文写具体的光和色>.
  Natural photographic rendering: rich but believable colour, real depth and local contrast, clean highlights, shadows with detail.
  Follow real light physics: keep the existing light direction and time of day, shadows stay darker and cooler than sunlit areas, sky graded naturally, reflections dimmer than the objects, no added light sources, no halos. Do not add a spotlight or a glow around the subject; dark backgrounds stay as dark and clean as in the source.
  No HDR look: do not lift the shadows evenly; keep the foreground and the deepest shadows as dark as in the source, or darker, as the black anchor of the frame; put the light only on the lit subject and the real light patches, so the contrast between light and shade stays the same or grows.
  Do not create a poster or graphic design. Do not add text.
  ```
  平的阴天、灰白天空：加一句 `keep the overcast sky smooth and soft, only a gentle gradient, do not add clouds`。不写“subtle / slightly”这类压低力度的词，也不写“颜色不要比原片浓”。
- 在手机正常尺寸下**对照原片**看 G 稿的**三条硬伤**：①明显的假光、光圈，或者整体不如原片；②keep 救不回来的大面积画崩；③大片涂抹发糊、像油画。返回拼图、多格或构图明显改变的直接作废。有硬伤或作废才补抽第 2 张（G 最多两张）。

**第 4 步 一条命令出片**

`python3 optional/pipeline.py 原片 G 参数.json 成片.png 回执.json --g-direct`（博物馆加 `--genre=museum`，夜景加 `--genre=night`；第 2 张 G 加 `--g-draw=2`）。它做对齐、keep 贴回、裁掉 G 没画到的窄边、构图裁切、高光保护，几秒钟跑完。**交不交付只看 `verdict`**：

- `DELIVER_G_DIRECT`：交付。色彩倍数、物理检查、接缝数值、`small_flags` 都只是记录，不是失败。但回执 `physics_final.serious` 里有 halo、spotlight_glow 或 sky_glow，或者 `drift.verdict` 是 `REPORT: non-sky chroma ratio` 时，交付前在成片上对照原片复看那个位置：有假光或过艳就按硬伤处理，补抽第 2 张；没问题就照常交付，回执第二行写“复看了某处：无问题”。
- `REDRAW_G: …`：G 返回了拼图或构图变了、对不上。按 `next` 补抽第 2 张，加 `--g-draw=2` 重跑。
- `DELIVER_QUICK_N (…)`：两张 G 都有硬故障，命令已自动交付快速 N 直出。照常交付，标签写 `N 直出`。

同一批里如果有一张连续两次返回拼图，后面的照片在调用 G 前先提醒用户一次“这个宿主请一张一张发”，然后照常逐张处理。

**第 5 步 交付**

每张**只交付一张成片**：一张原生图片，加一行 `看点：……｜风格：……`，再加成片标签 `G 直出 + 细节贴回` 或 `N 直出`，裁过的加 `＋重构`。宿主自动显示了 G 稿时，在成片前写“上面那张是中间稿，以下是成片”。回执只记两行，用户说“看回执”时再读 JSON 汇报：第一行“keep：编号—内容，已在预览图上核对”（或“无需保护”）；第二行“三条硬伤：无”或看到的问题，以及用了第几张 G。

## 4. 非生成式 / 严格保真 / 没有 G（T2）

用户要求“非生成式”“严格保真”，或者宿主没有 G 时，不调用 G。照样做第 1 步的构图判断（导演单的提升动作和 keep 可以省略），然后运行 `python3 optional/pipeline.py 原片 原片 参数.json 成片.png 回执.json --quick-n`：自动白平衡、去灰、色阶、对比度，再做构图裁切和高光保护，几秒钟出片，标签写 `N 直出`。参数里已有 `key_light` 就会用上，但不需要专门去写。

## 5. 必须遵守

- **不造光，也不删光**：亮只落在原本有光的地方；暗背景保持干净，不出现光圈、聚光灯效果（`references/physics.md`）。
- **人眼看不出即可**：所有判断以手机正常尺寸观看为准；1:1 下细碎枝叶略软可以接受。
- **不得改动或替代工具**：工具报错就如实报告，不写临时脚本修改或绕开工具。
- **如实标注**：N 直出不标成 G；没做的检查不说做了。
- **用户不满意**：用户说一句（“太暖了”“再通透一点”），就改这张的导演单重做。不把这句话当成以后所有照片的口味。
- 只支持从手机相册上传；宿主会压缩照片（长边约 1500 像素），不提示用户改用文件上传。

## 6. 工具与参考

| 文件 | 用途 |
|---|---|
| `optional/selfcheck.py` | 每条对话开头自检一次 |
| `optional/keep_preview.py` | 把 keep 框和 0.1 网格画在原片上，调用 G 前核对 |
| `optional/pipeline.py --g-direct` | 主线：对齐、贴回、裁窄边、构图、高光保护、硬故障时快速 N 直出 |
| `optional/pipeline.py --quick-n`、`optional/quick_n.py` | 非生成式 / 没有 G：快速 N 直出 |
| `references/reframe_rules.md` | 构图手法与必查项的完整版 |
| `references/physics.md` | 自然光的物理原则 |
| `references/capability_tiers.md`、`references/delivery.md` | 宿主分级、交付格式 |

`pipeline.py` 不加 `--g-direct` 或 `--quick-n` 时，仍是 v1.4 的旧默认路线（光色迁移 + 多轮调色），本文件不再使用，相关参考文件（`director_brief.md`、`n_grade.md`、`intensity.md` 等）只作历史记录。
