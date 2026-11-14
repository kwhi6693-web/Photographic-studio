# 专业知识二：诊断到处方（v0.3.0；v1.0.9 逐张诊断用）

读片时把这张表从上到下过一遍，只取这张照片**确实有**的问题（`director_brief.md` 第 1 节）。每条给出对 G 的说法和 N（`grade.py`）的参数范围：**问题轻取下端，重取上端**；没有的问题不取。一张照片可能只有一两条，也可能一条都没有。

| 诊断 | 判断依据 | 给 G 的说法（写进摄影意图） | N 的参数 |
|---|---|---|---|
| 主角不突出 | 眼睛先落在别处；主角和背景一样亮 | make the existing light on <主角> read clearly; quiet the surroundings; no spotlight, no glow | 先收周边：`vignette` 3–7（中心放在主角）、次要色 `hues` 收；主角只加 `clarity`／反差。只有主角本身受光时才可 `regions` 提亮 lift ≤4（v0.3.7：工具会让提亮只落在原本亮的地方；暗背景上禁止椭圆提亮） |
| 画面发灰 | 动态范围 < 60；没有黑也没有白 | restore full tonal range with real blacks and clean whites | `levels` 定黑白场；`contrast` 0.10–0.20 |
| 蒙雾、漏光（v1.0.9） | **缺陷性的**发白蒙层：隔着玻璃拍、逆光进镜头、镜头脏造成的整片发灰，近处的景物也一样发白，看起来像隔了一层纱；**画面里有纯黑的窗框或边框时动态范围仍会很宽，不能据此判断“不灰”**，以眼睛为准；镜头漏光是一侧发亮的斜带。**天气形成的雾**（晨雾、山岚、雨雾：近处清楚、越远越淡）是氛围，不属于这一条，见下一行 | clear the haze; deep, clean water and stone | `levels.black` 5–10、`contrast` 0.08–0.15、`saturation` 1.05–1.1；漏光一侧 `regions` gradient lift −4…−8 |
| 雾气是氛围（v1.0.9） | 天气形成的雾：近处清楚、越远越淡，远景层层退后 | keep the mist and the layers of distance | **不去雾**：只让近景略实（`clarity` ≤0.1 加近景 `regions`），远景保持淡；`levels.black` 不超过 2 |
| 光线已经很好（v1.0.9） | 光比、色彩、层次都已到位（例如逆光加斑驳日光） | keep the light as it is; only refine | 只做轻修：`highlights` −2…−4、`vibrance` ≤0.1、`clarity` ≤0.1；**不提亮、不加饱和** |
| 天空发白或平 | 天空 L* > 78 且色度 < 14 | give the sky depth and gradient | `regions` gradient from top lift −4…−8；`hues.blue` sat 1.15–1.3、lum −2…−6；`highlights` −4…−8 |
| 高光过曝 | 白色削波 > 0.5%；亮处没层次 | keep highlight detail | `highlights` −5…−12；不要再加 `exposure_ev` |
| 暗部死黑（且有内容值得看） | L* < 20 的面积 > 35% | open the shadows while keeping them dark | `shadows` 4–10；`tone_split.shadows` 略偏冷 |
| 暗部本来就是气氛 | 夜景、剪影、低调 | keep the darkness, shape the lit areas | 不提暗部；`contrast` 加在亮部；光源周围不提亮（会变成假光晕）|
| 色彩平淡 | 色度均值低，但场景本身有颜色 | richer, believable colour | `vibrance` 0.15–0.30；主色 `hues.<色>.sat` 1.1–1.3 |
| 色彩杂乱 | 三种以上颜色都很饱和 | simplify the palette around <主色> | 次要色 `hues.<色>.sat` 0.7–0.9；主色保持或略加 |
| 整体偏色 | b 均值明显偏暖/偏冷，与时段不符 | neutral, accurate white balance | `white_balance.temp` ±0.1–0.3 |
| 冷暖没有分开 | 暗部和亮部色温一样 | warm light against cool shade | `tone_split` 亮部 b +2…+4，暗部 b −2…−4 |
| 质感弱、发平 | 局部反差低；石材、木材、建筑细部不立体 | bring out the texture and volume of <材质> | `clarity` 0.15–0.35（只在需要处，可配 `regions`） |
| 空间扁平 | 前中后景明暗一样 | separate foreground, middle and distance with light and tone | 远景 `regions` 略降饱和、降反差（空气透视）；近景略压暗加反差 |
| 边缘抢戏 | attention 的 edge_pull > 1.15；边上有亮斑 | quiet edges | `vignette`；或用 `reframe.py` 裁掉 |
| 竖线倾斜、地平线歪 | 建筑线条汇聚；水平线不平 | （不交给 G） | `reframe.py` 拉直或透视矫正 |
| 主体太小、周围空 | 主角占画面很小且四周无信息 | （不交给 G） | `reframe.py` 裁切，保留成就看点所需的环境（极简看点时留白本身就是看点，不裁） |
| 夜景灯光溢出 | 光源周围一片白 | control the glow around lights | `highlights` −6…−12；`hues.yellow/orange` lum −3…−6 |
| 逆光主体太暗 | 主体是剪影但本应看清 | open the subject's shadow side gently, keep the backlight and the rim | `shadows` 4–8；需要时 `regions` 提亮主体 lift ≤6、`edge_aware: true`，提完主体仍比逆光背景暗 |
| 某种颜色过艳（v1.0.9） | 一种颜色明显比现实浓：荧光绿的树、发紫的天空、过头的晚霞、发橙的灯光 | keep <颜色> rich but believable | 只收那一种：`hues.<色>.sat` 0.8–0.92；不动其他颜色；天空、水面这类平滑大面积优先用 `regions` 加 `only_hue` 收 `sat` |
| 偏绿或偏品红（v1.0.9） | 白墙、灰石、白纸带绿或带紫红；荧光灯、LED、绿荫反射常见 | neutral whites | `white_balance.tint` ±0.05–0.2（偏绿往 + 调，偏品红往 − 调） |
| 混合色温（v1.0.9） | 暖灯和冷的窗光、天光同时出现 | keep warm lamps against cool daylight | **保留冷暖对比，不统一成一个色温**；只在一方偏得失真时，用 `regions` 的 `warm` 对那一块校正 ±2–4 |
| 室内外亮度差大（v1.0.9） | 室内正常、窗外一片白；或窗外正常、室内太暗 | hold the view outside, keep the room's light direction | 窗外：`highlights` −8…−15，必要时 `regions` 压窗 lift −4…−8；室内：`shadows` 3–6；保持“里暗外亮” |
| 天空亮、地面暗（v1.0.9） | 天空正常而地面、树林、建筑偏暗，或地面正常而天空发白 | balance sky and land, sky still lighter | 天空 `regions` gradient from top lift −3…−6；地面 `shadows` 3–6；天空仍要比地面亮（逆光剪影除外） |
| 白色发灰或偏蓝（v1.0.9） | 雪、白墙、白云、白瓷发灰或偏冷 | clean, bright whites | `levels.white` 92–97；`exposure_ev` +0.05–0.15（只在没有别的高光会过曝时）；偏蓝时 `white_balance.temp` +0.05–0.1 |
| 阴天光线平（v1.0.9） | 阴天、散射光，没有方向、没有影子 | gentle shape without inventing sun | `clarity` 0.1–0.2、`contrast` 0.05–0.1、轻微 `vignette` 2–4；**不加暖、不造阳光、不把阴天修成晴天** |

## 本工具处理不了的问题（v1.0.9）

下面这些问题，`grade.py` 和本包的其他工具都修不了。读片时看到了，就写进导演单的诊断里、标“不处理”，交付回执如实写明；**不用调色参数硬修，也不交给 G 重画**（G 会改动细节，带来 AI 味）。

| 问题 | 怎么认 | 为什么不处理 |
|---|---|---|
| 噪点 | 暗部、夜景、室内的颗粒和色斑 | 没有降噪工具；提暗部会让它更明显，所以诊断里有噪点时，`shadows` 少提 |
| 紫边、色差 | 高反差边缘的紫色、绿色镶边 | 没有色差校正工具 |
| 镜头畸变 | 广角桶形变形、边缘拉伸 | `reframe.py` 只能做透视矫正，不能校正畸变 |
| 失焦、运动模糊、手抖 | 主体不清楚 | 锐化不能找回丢失的细节，强锐化只会出白边 |
| 传感器污点、镜头脏点 | 天空或平滑区域的固定暗点 | 没有修补工具 |
| 摩尔纹、LED 色带 | 细密织物或屏幕上的波纹；灯光下的横向色带 | 没有对应工具 |
| 拍摄角度、景深 | 想换视角、想要更虚的背景 | 只能拍摄时决定 |

## 不要做的

- **v0.3.8**：天空、水面、白墙这类淡色平滑区域，少用 `hues` 去压颜色（容易出色块）；颜色过浓优先用 `vibrance` 或 `saturation` 整体收。`grade.py` v0.3.8 已把按颜色调整做平滑，但力度大时仍要在 100% 下看一眼。

- **不造光（v0.3.7）**：突出主角靠“收周边”和“放大主角身上已有的光”，不靠给主角周围加一圈亮。暗背景（展柜、夜空、黑墙）保持原片的暗，不出现椭圆光圈、聚光灯效果；也不在画面局部压出暗斑。
- 任何一条处方都不能违反 `physics.md` 的自然物理原则：提亮要跟着光走，阴影要比受光面暗、冷，天空上深下浅，倒影比实物暗，不加光源（v0.3.6）。

- 不要同时把 `contrast`、`clarity`、`saturation` 都加满：先定明暗，再定颜色，最后才是质感。
- 不要把每个问题都修到“标准”：有气质的不完美（雾、暗、偏色的黄昏）比标准答案值钱。
- 提亮暗部会带出噪点和灰；提多少看暗部里有没有值得看的东西。
- 局部调整的边界要柔（`feather` ≥ 0.08）或沿物体边缘（`edge_aware`），否则看得出一块一块。
