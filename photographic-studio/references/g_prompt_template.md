# G 路线调用规范与提示模板（v0.2.1）

> 来源与边界：本模板按 WO-1/2/3 实测过的提示结构**重建**，不是任何一次调用的逐字原文。宿主会改写提示词，实际可见调用文本通常与此不同。除庭院测试外，A（天空/穹顶）、B（石墙）、C（室内拱廊）三张新照片首轮被用户接受；样本很少，不构成稳定性保证。

## 1. 调用前

1. 当次原片必须出现在**最近一条用户消息**的附件里，紧邻调用。这是实测中使用的条件；已有的证据是输出与原片结构高度对应（相关 0.87–0.97，ORB 内点 475–1261，无关图约 0 / ≤15）。元数据（edit_op、gen_id、seed）**不能**证明绑定，不要用它声称绑定。
2. 调用前用一行话向用户写明意图（原片、目标、保护项）。
3. 提示词必须是**修图指令**。不得出现把"报告、海报、信息图、验证"当作要求的句子。仅以否定形式出现的一句 "Do not create a poster, document, infographic, collage, or any graphic design" 允许保留（实测使用过）。

## 2. 模板（v0.2.1：表现力优先；v0.3.0：由导演单驱动）

v0.3.6：“摄影意图”之后必须加 `physics.md` 第 2 节的那一句（遵循真实的光：保持光的方向和时刻、阴影比受光面暗且冷、天空自然渐变、倒影比实物暗、不加光源、不出光晕）。
v0.3.7：那一句后面还有第二句，**必须一起写**：`Do not add a spotlight or a glow around the subject; dark backgrounds stay as dark and clean as in the source.`

v0.3.3：默认路线只取 G 的**光线和色彩**（`look_transfer.py`），G 画的纹理不会进入成片。所以提示词把力气放在光色上：光的方向、冷暖、明暗分布、主角的光、天空和水的颜色。不要求 G 刻画材质细节、加云、加光束——这些带不进成片，只会让 G 偏离原片、降低光色迁移的质量。走升级路线时才按下文追求材质表现。

v0.3.0：“摄影意图”一行直接来自导演单的“看点｜风格”“主角”“影调”“色彩”四行（`director_brief.md` 第 3 节）；G 指宿主自带的、能以原片为输入的图像编辑工具，不限定厂商。

v0.2.1 起，关键细节由贴回兜底（`detail_restore.md`），**G 的提示词不再以“克制、保守、只做色调”为目标**。G 的任务是把这张照片做成有专业摄影表现力的成片；提示词只约束“不改取景、不改布局”，因为贴回需要与原片对齐。

```
Edit the provided photo into a finished, professional-grade photograph with strong but natural photographic impact.
Image A is the direct source photo. Keep the same framing, viewpoint and layout of everything in the scene.
Make the light and colour work: <本张的 2–3 项摄影意图，例如 shape the light on the facade and give the sky depth / warm sunlit stone against cool shade / separate the subject from the background with light and tone>.
Natural photographic rendering: rich but believable colour, real depth and local contrast, clean highlights, shadows with detail.
Do not create a poster, collage or graphic design. Do not add text.
```

写“摄影意图”一行的要求：
- v0.2.2：把 `story_style.md` 定下的风格方向翻译成具体的光色手段，并点出主角。例：`Warm late-afternoon documentary mood: keep the low sun and long shadows, keep the warm light on the old shopfronts, the street as the subject`。
- **v0.3.8：提示词里不写数字目标**（例如“提亮 7 L*”“两倍亮度”“色彩浓 20%”）。图像模型执行不了数字，数字只会让 G 偏离；数字目标只写在导演单里，由 `grade.py` 和检查工具实现。
- **v0.3.8：保留真实的反光和高光**：在“摄影意图”里写 `keep the real glaze, glass and metal highlights and the existing light patches in the scene`；不写 “controlled specular highlights”，那会让 G 压掉釉光。
- 来自 A 阶段对原片的观察：主体、光线方向、冷暖关系、空间层次。写具体的光和色，不写“subtle / slightly / only tonal”这类压低强度的词。
- 不再默认加文字、石材、人物保护行：这些由贴回负责。只有当某个物体**无法贴回**（例如大面积招牌超过画面三分之一）时，才加一行 `Keep <对象> exactly as in the source.`

## 3. 强度（宿主没有强度参数，只靠措辞）

- 历史参照（用户认可过的样本）：A 天空色度 ×2.05；C L* +9.04、色度 ×1.33；WO-8 建筑、夜景、运河用户评价“很满意”。v0.2.0 批次的提示词写成 “Subtly clarify… tonal refinement only”，多数输出 L* 只有 +1 到 +3、色度 ×1.0–1.35，用户评价降为“比较满意”。
- **强度不足的判定以人眼为准**：正常观看下成片和原片相比，看不出明显的光影或色彩提升。可参考数字（只标记，不是门槛）：|ΔL*| < 2 且色度 < ×1.25。
- 强度不足时，可以把“摄影意图”写得更具体、更有方向，用同一原片重跑一次 G（计入下面第 5 节的“最多两次”）。
- 过强（假 HDR、塑料感、天空不真实）时同样可重跑一次，删去最强的一项意图。

## 4. 调用后记录（不做一致性评判）

- 记录：可见调用文本、返回的文件名/大小/SHA256。
- 不要求可见文本与模板相同；宿主改写属已观察到的常态。
- 不得把"文本一致"或元数据当作通过条件。

## 5. 失败处理

- 场景对应检查不过：**STOP**，如实报告，不作为成片交付。比例偏差超过 ±0.02 在 v0.2.0 起只标记。
- **G 最多调用两次**（v0.2.1）：第一次结果强度不足、过强，或因 G 改动过大（重画结构、物体增删或移位、颜色大幅偏离）导致贴回后仍不合格时，可以调整提示词重跑一次，写明改了什么、为什么。第二次仍不行就按总则处理（STOP 或带标记交付），不静默换 N。
- 输出类型错误（出现海报、文档、拼图）：STOP，并检查是否是调用文本问题。
