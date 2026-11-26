---
name: photographic-studio
description: 独立的非人像摄影后期工作流，面向任何能看图的 agent。用户发来一张或多张照片并要求修图（例如“修”“修一下这张”“修成成片”）时使用，适用于建筑、街景、风光、园林、夜景、室内、静物、展品等非人像照片。大模型读片、写导演单、定构图，宿主的图像编辑工具出片，确定性工具贴回关键细节、裁切、保护高光、拦下硬故障，直接交付一张成片；按宿主实际具备的工具分级执行。
---

# Photographic Studio v1.6.3

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

1. **看点与导演单**：先读所属题材的**一页** `references/genres/`（园林、建筑、室内、风光、夜景、静物、街头选一页；页里的 `clarity`、`regions` 等 N 参数属于旧路线，忽略），照它的看点和常见错误来写。一句“看点｜风格”（看点不只是叙事，还有几何、光影、色彩、质感、氛围），再写 **2–4 个具体的提升动作**，每个说清对谁、往哪个方向：
   - **第 1 个固定写主光**：光聚到主角上，四周和暗部保持原片的暗，或者更暗；
   - 其余 1–3 个按需要选：分离（主体与背景拉开明暗或冷暖）；色彩（理顺主色、压住抢眼的杂色、受光面暖、阴影偏冷）；纵深与氛围（远景更通透或更有雾感，天空从上往下自然加深）。
   只写方向，不写数字。动作要让成片在正常尺寸下一眼看得出比原片好。
   **动作只动光和色**（光的方向、明暗分布、冷暖、主体分离、远近的明暗）。不要求 G 刻画材质细节、补出暗处看不清的纹理、加光束、星芒或光泽：这些会让 G 脑补，成片像渲染图。屋檐下、窗框、厅堂、暗角这类暗调本来就是气氛：保持暗而干净，不提亮成灰。
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
  Natural photographic rendering: rich but believable colour, real depth and local contrast, clean highlights; shadows keep only the detail already visible in the source.
  Only change light, tone and colour. Dark shadows stay as dark and plain as in the source. Surfaces keep their real finish: matte wood, paint and stone stay matte. Small light points stay small soft glows. It should look like a real camera photo, not a 3D render.
  Follow real light physics: keep the existing light direction and time of day, shadows stay darker and cooler than sunlit areas, sky graded naturally, reflections dimmer than the objects, no added light sources, no halos. Do not add a spotlight or a glow around the subject; dark backgrounds stay as dark and clean as in the source.
  No HDR look: do not lift the shadows evenly; keep the foreground and the deepest shadows as dark as in the source, or darker, as the black anchor of the frame; put the light only on the lit subject and the real light patches, so the contrast between light and shade stays the same or grows.
  Do not create a poster or graphic design. Do not add text.
  ```
  平的阴天、灰白天空：加一句 `keep the overcast sky smooth and soft, only a gentle gradient, do not add clouds`。原片一半以上很暗（逆光、屋檐下、暗角多的室内）：把 `real depth and local contrast` 改成 `real depth`。不写“subtle / slightly”这类压低力度的词，也不写“颜色不要比原片浓”。
- 在手机正常尺寸下**对照原片**看 G 稿的**四条硬伤**：①明显的假光、光圈，或者整体不如原片；②keep 救不回来的大面积画崩；③大片涂抹发糊、像油画；④脑补或渲染感：原片里看不清的暗处出现了新纹理、新图案，或者出现原片没有的星芒、光束、塑料或镜面高光，整体像 3D 渲染；或者整张画面被刷成单一色调、时间感错乱，原本真实的冷暖并存、表面色差与自然旧痕被抹平洗净，像样板间或 3D 渲染图。只是变亮不算第④条；顺着原片已有光的方向、柔和自然地加强或延伸的光（例如斜阳落在墙面、地面上的光带）也不算。返回拼图、多格或构图明显改变的直接作废。有硬伤或作废才补抽第 2 张（G 最多两张）。

**第 4 步 一条命令出片**

`python3 optional/pipeline.py 原片 G 参数.json 成片.png 回执.json --g-direct`（博物馆加 `--genre=museum`，夜景加 `--genre=night`；第 2 张 G 加 `--g-draw=2 --g-prev=第1张G的文件`）。它做对齐、keep 贴回、裁掉 G 没画到的窄边、构图裁切、高光保护，几秒钟跑完。**交不交付只看 `verdict`**：

- `DELIVER_G_DIRECT`：交付。回执 `next` 里有“哨兵提醒”时（v1.6.0，只报不拦：G 的细纹理明显比原片强，或原片很暗处多出了细节），先按提醒去那个位置对照原片看一眼：确认是第④条硬伤就补抽第 2 张，没问题就照常交付，回执第二行写“复看了某处：无问题”。色彩倍数、物理检查、接缝数值、`small_flags` 都只是记录，不是失败。但回执 `physics_final.serious` 里有 halo、spotlight_glow 或 sky_glow，或者 `drift.verdict` 是 `REPORT: non-sky chroma ratio` 时，交付前在成片上对照原片复看那个位置：有假光或过艳就按硬伤处理，补抽第 2 张；没问题就照常交付，回执第二行写“复看了某处：无问题”。
- `REDRAW_G: …`：G 返回了拼图或构图变了、对不上。按 `next` 补抽第 2 张，加 `--g-draw=2 --g-prev=第1张G的文件` 重跑。
- `DELIVER_LOOK (…)`（v1.6.3）：成片的每个像素都是原片的，只借 G 的光和颜色。命令自己判断，不用执行模型估：原片极暗、或 keep 框合起来超过画面 40% 时，第 1 张 G 回来就直接走这条（**不再补抽第 2 张**）；G 直出彻底失败时也先走这条。照常交付，标签写 `原片像素 + G 光色`。
- `DELIVER_QUICK_N (…)`：连“原片像素 + G 光色”也做不成（G 稿完全对不上原片）时，命令自动交付快速 N 直出。照常交付，标签写 `N 直出`。

同一批里如果有一张连续两次返回拼图，后面的照片在调用 G 前先提醒用户一次“这个宿主请一张一张发”，然后照常逐张处理。

**第 5 步 交付**

每张给**一张成片**，加一行 `看点：……｜风格：……`，再加成片标签 `G 直出 + 细节贴回`、`原片像素 + G 光色` 或 `N 直出`，裁过的加 `＋重构`。
- **成片和中间稿都要能点开、能直接存进手机“照片”App**（v1.6.0，用户 2026-11-26 iPhone 实测：代码在对话里显示的图存不了，.jpg 链接点开后可以存）。所以：用 `python3 optional/to_jpeg.py 成片.png 成片_编号.jpg` 转成 JPEG（原尺寸、质量 95），以**可点击的 .jpg 链接**交付；用了 G 的，把实际用的那张 G 稿也同样转成 `中间稿_编号.jpg` 给链接，标明“中间稿”。不要用代码把图片显示在对话里代替链接。
- 存进手机“照片”的说法按宿主写（`references/delivery.md`）。ChatGPT iPhone App 实测：G 中间稿可以直接长按存；.jpg 链接点开后存进的是“文件”，链接下面写一句：“点开链接存到文件 → 在‘文件’里打开 → 分享 → 存储图像，就进了照片”。
- 宿主自动显示了 G 稿时，在成片链接前写“上面那张是中间稿，以下是成片”。回执只记两行，用户说“看回执”时再读 JSON 汇报：第一行“keep：编号—内容，已在预览图上核对”（或“无需保护”）；第二行“四条硬伤：无”或看到的问题，以及用了第几张 G。

## 4. 非生成式 / 严格保真 / 没有 G（T2）

用户要求“非生成式”“严格保真”，或者宿主没有 G 时，不调用 G。照样做第 1 步的构图判断（导演单的提升动作和 keep 可以省略），然后运行 `python3 optional/pipeline.py 原片 原片 参数.json 成片.png 回执.json --quick-n`：自动白平衡、去灰、色阶、对比度，再做构图裁切和高光保护，几秒钟出片，标签写 `N 直出`。参数里已有 `key_light` 就会用上，但不需要专门去写。

## 5. 必须遵守

- **不凭空造光，也不删光**：可以顺着原片已有光的方向、柔和地加强或延伸光；不凭空造新光源，不加星芒、光束、光圈、聚光灯效果；暗背景保持干净（`references/physics.md`；两者不一致时以本条为准）。
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
| `optional/pipeline.py --quick-n`、`optional/quick_n.py` | 非生成式 / 没有 G：快速 N 直出（v1.6.0：极暗原片自动提一点层次） |
| `optional/to_jpeg.py` | v1.6.0：成片、中间稿转 JPEG，作为可点击链接交付，iPhone 上能存进照片 App |
| `optional/look_route.py` | v1.6.3：“原片像素 + G 光色”路线（由 `pipeline.py` 自动调用，内部用 `look_transfer.py`） |
| `optional/sentinel.py` | v1.6.0：g-direct 自动运行的两个只读哨兵（纹理重画、暗部脑补），结果写进回执 |
| `references/reframe_rules.md` | 构图手法与必查项的完整版 |
| `references/physics.md` | 自然光的物理原则 |
| `references/capability_tiers.md`、`references/delivery.md` | 宿主分级、交付格式 |

v1.6.2：v1.4 的旧默认路线（`finish.py`、`settle.py`、`harmonize.py` 等）和只服务于它的参考文件（`director_brief.md`、`n_grade.md`、`intensity.md`、`g_prompt_template.md` 等）已移出安装包，归档在仓库的 `legacy/v1.4/`。参考文件里如果还提到这些文件，忽略即可，不用去找。`pipeline.py` 必须带 `--g-direct` 或 `--quick-n`。
