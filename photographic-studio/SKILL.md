---
name: photographic-studio
description: 独立的非人像摄影后期工作流，面向任何能看图的 agent。用户发来一张或多张照片并要求修图（例如“修”“修一下这张”“修成成片”“精修”）时使用，适用于建筑、街景、风光、园林、夜景、室内、静物、展品等非人像照片。自动读片、写导演单、指挥生成式光色与确定性调色、检查是否符合自然光的物理规律和用户偏好的力度，直接交付一张成片；按宿主实际具备的工具分级执行。
---

# Photographic Studio v1.0.4

用户发来照片、说一句“修”，就得到这个 agent 能做出的最好一张成片。成片要**有明显的摄影表现力**、**仍然高度像原片**、**符合真实光线的物理规律**，并且**看不出 AI 痕迹**。表现力第一；其余三条是同时成立的约束。

本文件是唯一的执行说明。`references/principles.md` 是总则；其他参考文件给细节。参考文件里留有版本号和日期，只说明那条规则从哪来；**与本文件或总则冲突时，以本文件和总则为准**。

## 1. 边界

- 只做非人像。偶然入镜的人物保持原样：不美化、不塑形、不推断身份。主体是人像时不修，一句话说明。
- 独立产品：不调用、不依赖、不修改任何其他摄影 Skill。
- 用户发来照片并要求修图，即视为对这张照片的当次编辑授权。只要求分析时不编辑；要求严格保真、非生成式时不用 G，直接 N 直出。
- 照片不留作风格库或训练素材；不外发到第三方服务。
- 不能保证每次都达到参照样本的水平；用户有最终接受权。

## 2. 名词

- **G**：宿主自带、能以原片为输入的图像编辑工具（不限厂商）。默认路线只取 G 的**光线和色彩**，不取它画的像素。
- **N**：本包 `optional/` 里的确定性工具，不生成内容。
- **成片标签**：`原片像素 + G 光色 → N 精修`（默认）｜`N 直出`（没有 G、G 不合格或用户要求非生成式）｜`G + 细节贴回`（升级路线），可加后缀 `＋重构`、`＋防过冲`。

## 3. 默认执行（不问问题、不要工单；多张逐张处理）

**眼睛和大脑**
1. **自检定级**：运行 `optional/selfcheck.py`，再确认自己有没有 G，按 `references/capability_tiers.md` 定级（T1 有 G 且能跑代码；T2 只能跑代码；T3 只有 G；T4 都没有）。缺依赖且宿主允许时先安装再自检一次。级别写进回执。
2. **测量**：`optional/measure.py 原片`。
3. **读片**：故事、情绪、主角、风格方向（`references/story_style.md`）；光、色、影调、引导、空间（`references/craft_reading.md`）；只读所属题材一页（`references/genres/`）；看一眼口味参照（`references/taste_profile.md`）。
4. **写导演单**：六行（`references/director_brief.md`），对照 `references/craft_prescriptions.md` 翻译成给 G 的提示词和给 N 的参数。数字目标只写在导演单和 N 参数里，**不写进 G 的提示词**。

**手**
5. **出片（T1）**：
   - 调用 G 一次。原片必须在最近一条用户消息里；提示词按 `references/g_prompt_template.md`，必须包含 `references/physics.md` 第 2 节的两句物理要求。调用后用 `optional/check_g_output.py` 检查场景是否对得上（`references/g_post_check.md`），对不上就作废这一版。
   - 运行 **`optional/finish.py 原片 G 参数.json 成片.png 回执.json`**；博物馆、展柜、低调静物加 `--genre=museum`。它依次做光色迁移（`look_transfer.py`：成片的每个像素来自原片，只带 G 的光和色，并拦下 G 凭空加的光和删掉的光）、精修（`grade.py`）、物理检查、强度检查。**物理检查通过、强度在范围内、且看得出变化**才算合格；不合格时自动按阶梯重做：原参数 → 博物馆力度（仅 museum）→ 去掉正向区域提亮和暗角 → `--local=0` → N 直出 → N 直出 + 博物馆力度。交付第一张合格的；都不合格时，**通过物理检查且看得出变化的 G 路线优先于 N 直出**（力度超出范围只写进回执，由第 6 步只去掉超出的部分，不是放弃 G 的理由），其余情况交付问题最少的一张，回执列出问题。**不停下来问用户。**
   - T2：没有 G，直接 `finish.py 原片 原片 参数.json …`（等于 N 直出，`references/n_grade.md`）。T3：只有 G，交付 G 的输出并如实标注没有做检查。T4：只给读片和建议。
6. **验收**（必做，写进回执，默认不显示）：拿成片逐行对照导演单，按 `director_brief.md` 第 4 节写七项结论（故事风格｜主角｜影调｜色彩｜不能动｜构图｜自然度）和一个决定。自然度见 `references/naturalness.md`。
   - 方向对、程度不够 → `grade.py` 补齐（最多 3 轮），每轮后 `intensity_check.py 原片 新版 --before=上一版`。总结论是 `DO_NOT_DELIVER` 的一轮必须撤回。
   - G 的光色方向本身不对 → 改提示词再调用一次 G（G 最多两次），重新跑 `finish.py`，两版取更好的一张。
   - 升级路线：只有当默认路线缺的正是 G 像素才有的效果（例如重新塑造的天空层次；不包括原片没有光源的光束、光圈），且 G 通过自然度检查时，才改用 G + 关键细节贴回（`references/detail_restore.md`），与默认版比较取更好的一张。
7. **构图与收尾**：按导演单做几何构图优化（`references/reframe_rules.md`，`optional/reframe.py`：只裁剪、拉直、透视矫正）；做了就再跑一次 `physics_check.py` 和 `intensity_check.py`（博物馆加 `--genre=museum`）；最后 `optional/n_trim.py` 检查高光过冲（`references/n_trim.md`）。
8. **交付**：**只交付一张成片**——一张原生图片，加一行 `故事：……｜风格：……`，再加成片标签。宿主自动显示了 G 的中间稿时，在成片前写“上面那张是中间稿，以下是成片”。其余一概不显示（`references/delivery.md`）。

**拿不到成片的情况只有**：主体是人像；原片读不了；T4；用户只要分析。用一句话说明。

## 4. 必须遵守的几条

- **不造光，也不删光**（`references/physics.md`）：加亮只落在原本有光的地方；暗背景保持原片的暗和干净，不出现光圈、椭圆亮区、聚光灯效果；也不把原片里真实的光斑、反光、釉光压掉。
- **力度按用户偏好**（`references/intensity.md`）：下限是表现力底线，必须达到；上限只去掉超出的部分。博物馆题材按主角判断（用户选定的第 3 档）。
- **人眼看不出即可**：所有判断以整图正常观看为准，200% 只用来确认已发现的问题。
- **不得改动或替代工具**：工具报错或缺失时如实报告，不写临时脚本修改工具。
- **如实标注**：N 的结果不标成 G；没做的检查不说做了。

## 5. 其他模式（用户要求时）

- **“精修”**：第 5 步出 2 个 G 方向（忠于原片气质、更大胆）加 1 个 N 直出，各自跑 `finish.py`，按导演单和口味参照选一张，再做第 6–8 步。更慢、更耗额度。
- **“看回执”**：导演单、G 提示词、参数、`finish.py` 回执、检查结论、哈希。
- **“看标记表”**：累计标记表（`references/flag_log_template.md`）。
- **“验证批次”**：按 `references/validation_protocol.md`。
- **用户不满意**：用户说一句（“太暖了”“再通透一点”），就改导演单重做，并按 `taste_profile.md` 第 3 节记下这条口味。

## 6. 上传与尺寸

只支持从手机相册上传照片（用户 2026-11-11 决定）。宿主会压缩上传的照片（实测长边约 1536 像素）；默认路线的成片与收到的原片同尺寸。不提示用户改用文件方式上传。

## 7. 参考文件

| 文件 | 内容 |
|---|---|
| `references/principles.md` | 总则：目标、三条原则、作废与保底、标记 |
| `references/capability_tiers.md` | 按宿主能力分四级 |
| `references/story_style.md` | 读片：故事、情绪、主角、风格方向 |
| `references/craft_reading.md`、`references/craft_prescriptions.md`、`references/genres/` | 读片要点、诊断到处方、六类题材 |
| `references/director_brief.md` | 导演单六行、翻译成指挥、验收七项 |
| `references/g_prompt_template.md`、`references/g_post_check.md` | G 的提示词与生成后检查 |
| `references/physics.md` | 自然光的物理原则与检查 |
| `references/intensity.md` | 用户偏好的力度范围与校准 |
| `references/n_grade.md` | `grade.py` 参数与用法 |
| `references/naturalness.md` | 自然度：AI 味的检查与局部修补 |
| `references/detail_restore.md` | 升级路线的关键细节贴回 |
| `references/reframe_rules.md` | 几何构图优化 |
| `references/n_trim.md` | 最后的高光过冲检查 |
| `references/taste_profile.md`、`assets/taste/` | 用户认可的成片与口味记录 |
| `references/delivery.md` | 交付格式与保存边界 |
| `references/validation_protocol.md`、`references/flag_log_template.md` | 验证批次与标记表 |
