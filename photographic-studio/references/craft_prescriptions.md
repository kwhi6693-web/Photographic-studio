# 专业知识二：诊断到处方（v0.3.0）

读片找到问题后查这张表。每条给出对 G 的说法和 N（`grade.py`）的参数方向。数值是起点，按人眼调整；一张照片通常只需要其中三到五条。

| 诊断 | 判断依据 | 给 G 的说法（写进摄影意图） | N 的参数 |
|---|---|---|---|
| 主角不突出 | 眼睛先落在别处；主角和背景一样亮 | make the existing light on <主角> read clearly; quiet the surroundings; no spotlight, no glow | 先收周边：`vignette` 3–7（中心放在主角）、次要色 `hues` 收；主角只加 `clarity`／反差。只有主角本身受光时才可 `regions` 提亮 lift ≤4（v0.3.7：工具会让提亮只落在原本亮的地方；暗背景上禁止椭圆提亮） |
| 画面发灰 | 动态范围 < 60；没有黑也没有白 | restore full tonal range with real blacks and clean whites | `levels` 定黑白场；`contrast` 0.10–0.20 |
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
| 主体太小、周围空 | 主角占画面很小且四周无信息 | （不交给 G） | `reframe.py` 裁切，保留讲故事所需的环境 |
| 夜景灯光溢出 | 光源周围一片白 | control the glow around lights | `highlights` −6…−12；`hues.yellow/orange` lum −3…−6 |
| 逆光主体太暗 | 主体是剪影但本应看清 | open the subject's shadow side gently, keep the backlight and the rim | `shadows` 4–8；需要时 `regions` 提亮主体 lift ≤6、`edge_aware: true`，提完主体仍比逆光背景暗 |

## 不要做的

- **v0.3.8**：天空、水面、白墙这类淡色平滑区域，少用 `hues` 去压颜色（容易出色块）；颜色过浓优先用 `vibrance` 或 `saturation` 整体收。`grade.py` v0.3.8 已把按颜色调整做平滑，但力度大时仍要在 100% 下看一眼。

- **不造光（v0.3.7）**：突出主角靠“收周边”和“放大主角身上已有的光”，不靠给主角周围加一圈亮。暗背景（展柜、夜空、黑墙）保持原片的暗，不出现椭圆光圈、聚光灯效果；也不在画面局部压出暗斑。
- 任何一条处方都不能违反 `physics.md` 的自然物理原则：提亮要跟着光走，阴影要比受光面暗、冷，天空上深下浅，倒影比实物暗，不加光源（v0.3.6）。

- 不要同时把 `contrast`、`clarity`、`saturation` 都加满：先定明暗，再定颜色，最后才是质感。
- 不要把每个问题都修到“标准”：有气质的不完美（雾、暗、偏色的黄昏）比标准答案值钱。
- 提亮暗部会带出噪点和灰；提多少看暗部里有没有值得看的东西。
- 局部调整的边界要柔（`feather` ≥ 0.08）或沿物体边缘（`edge_aware`），否则看得出一块一块。
