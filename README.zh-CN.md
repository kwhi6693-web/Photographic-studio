<p align="center">
  <img src="docs/images/banner.zh-CN.svg" alt="Photographic Studio — 一句「修」，一张成片" width="100%">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <b>简体中文</b> ·
  <a href="README.zh-TW.md">繁體中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.8-c8963e?style=flat-square" alt="version 1.0.8">
  <img src="https://img.shields.io/badge/Agent%20Skill-SKILL.md-1d2f63?style=flat-square" alt="Agent Skill">
  <img src="https://img.shields.io/badge/非人像-建筑·街景·风光·夜景·展品-3a5ba8?style=flat-square" alt="非人像">
  <img src="https://img.shields.io/badge/python-numpy·Pillow·OpenCV-2b3a55?style=flat-square" alt="numpy Pillow OpenCV">
  <img src="https://img.shields.io/badge/license-AGPL--3.0-c8963e?style=flat-square" alt="AGPL-3.0">
</p>

<p align="center">
  <b>发一张照片，说一个字：「修」。</b><br>
  它会像一位后期摄影师那样先读懂这张照片，再交给你一张——<br>
  <b>看得出提升、仍然是你拍的那一刻、光线讲得通、看不出 AI 痕迹</b>——的成片。
</p>

---

## 🎞️ 前后对比

> 左为原片，右为成片。照片都是作者自己拍的，成片经作者亲自挑选认可。

<table>
  <tr>
    <td width="50%"><img src="photographic-studio/assets/taste/02_night_before_after.jpg" alt="夜色中的塔与倒影"><br><sub><b>夜色中的塔与倒影</b> · 保住夜空的黑，让塔、桥和倒影的灯更清楚</sub></td>
    <td width="50%"><img src="photographic-studio/assets/taste/03_canal_before_after.jpg" alt="运河与云"><br><sub><b>运河与云</b> · 天空有了颜色和体积，树从死黑里透出层次</sub></td>
  </tr>
  <tr>
    <td><img src="photographic-studio/assets/taste/05_bronze_ox_before_after.jpg" alt="错金银铜牛灯"><br><sub><b>错金银铜牛灯</b> · 铜色、绿锈、赭红分明，黑墙依旧干净</sub></td>
    <td><img src="photographic-studio/assets/taste/06_blue_vase_museum_before_after.jpg" alt="蓝釉金彩瓶"><br><sub><b>蓝釉金彩瓶</b> · 钴蓝更浓、金饰更亮，展柜的暗一点不提</sub></td>
  </tr>
  <tr>
    <td><img src="photographic-studio/assets/taste/01_building_before_after.jpg" alt="铁塔框景里的钟楼"><br><sub><b>铁塔框景里的钟楼</b> · 夕阳的暖与钢架的冷拉开</sub></td>
    <td><img src="photographic-studio/assets/taste/04_willow_lake_before_after.jpg" alt="垂柳与湖"><br><sub><b>垂柳与湖</b> · 克制的清透，晴日里的安静</sub></td>
  </tr>
</table>

---

## 🎬 它怎么修一张照片

<p align="center">
  <img src="docs/images/pipeline.zh-CN.svg" alt="读片 → 导演单 → 只借光与色 → 精修与检查 → 一张成片" width="100%">
</p>

**1 · 读片**　先回答“这张照片在讲什么”：故事、情绪、主角、风格方向；再看光从哪来、颜色怎么搭、空间怎么分层。

**2 · 导演单**　把判断写成六行后期方案，例如：

```text
故事｜风格：暗展柜中，蓝釉与金饰承接展灯｜低调博物馆静物，深蓝与暖金分明
主角：中央蓝釉瓶；怎么突出：放大已有受光面的体积与金饰反差，背景保持深暗
影调：黑场保留，高光轻压，主体中间调展开，局部反差增加
色彩：钴蓝与暖金为主，加强釉色与金饰，收敛台座偏色
不能动：瓶形、纹样、顶珠、展签、玻璃里的真实反光
构图：保持——线图、瓶子与右侧映像共同交代展陈
```

**3 · 只借 AI 的光与色**　让宿主的图像模型出一版，但**只拿走它的光线和色彩**，成片的每一个像素仍然来自原片——文字、人物、纹理都是你拍到的那些。

**4 · 精修与检查**　确定性调色工具按导演单补齐，再过两道关：

- **物理关**：加亮只落在原本有光的地方；不给展品凭空加光圈，也不把真实的光斑、釉光抹掉；明暗次序、天空渐变、倒影都要讲得通。
- **力度关**：看得出提升，又不过头；博物馆展品按主角来判断。

不合格？它会自己换一级更稳的做法重来，直到交出一张合格的成片——**不停下来问你**。

**5 · 一张成片**　只交一张图，配一行 `故事｜风格`。

---

## 🧭 它坚持的四件事

| | |
|:--:|---|
| 🔆 | **表现力第一**——“改了等于没改”算失败。 |
| 📷 | **还是你拍的那一刻**——同一场景、同一时刻、同一视角。 |
| 🕯️ | **光要讲得通**——放大照片里本来就有的光，不画现实中不存在的光。 |
| 🍃 | **看不出 AI**——没有磨皮感、塑料感、假细节、假 HDR。 |

---

## 🚀 开始使用

**作为 Agent Skill 安装**：把 [`photographic-studio/`](photographic-studio) 整个目录安装到支持 `SKILL.md` 的宿主，然后：

```text
（发一张照片）修
```

**不能安装的宿主**：把目录打包成 zip，作为附件发过去，说一句：

```text
按附件里的 Photographic Studio 处理这张照片
```

### 口令

| 你说 | 它做 |
|---|---|
| `修` | 读片 → 导演单 → 出片 → 检查 → 交一张成片 |
| `精修` | 多出几个方向，比较后挑最好的一张（更慢） |
| `太暖了` · `再通透一点` | 按你的话改导演单重做，并记住这条口味 |
| `看回执` | 导演单、提示词、参数、检查结论 |
| `看标记表` | 每张照片的处理标记汇总 |

### 能力分级

它会先看宿主有什么工具，再决定怎么做：

| 级别 | 宿主能力 | 出片方式 |
|:--:|---|---|
| **T1** | 有图像编辑模型，也能运行 Python | 原片像素 + AI 光色 → 精修 |
| **T2** | 只能运行 Python | 确定性调色直出 |
| **T3** | 只有图像编辑模型 | 直接用模型的结果，并如实说明 |
| **T4** | 都没有 | 给出读片与后期建议 |

---

## ⚙️ 引擎（v2.0.0，原型）

同一套流程写成代码，不依赖 ChatGPT：读片和 G 调用模型 API，其余全部用确定性工具；附评测程序和给未来 App 用的 HTTP 服务骨架。API 密钥特意留空，见 [`engine/README.md`](engine/README.md)。

## 🗂️ 仓库结构

```text
photographic-studio/          ← Skill 本体（安装这个目录）
├── SKILL.md                  ← 执行说明，入口
├── references/               ← 总则、读片与处方、六类题材、导演单、物理、力度、交付……
│   └── genres/               ← 建筑 · 街景 · 风光 · 夜景 · 室内 · 静物与展品
├── optional/                 ← 工具（numpy · Pillow · OpenCV）
│   ├── finish.py             ← 一步出片，含自动重做阶梯
│   ├── look_transfer.py      ← 原片像素 + AI 光色
│   ├── grade.py              ← 按导演单调色
│   ├── settle.py             ← 一次完成力度校准
│   ├── physics_check.py      ← 自然光物理检查
│   └── intensity_check.py    ← 力度检查
├── assets/taste/             ← 口味参照：作者认可的前后对比
├── CHANGELOG.md
└── SHA256SUMS.txt
docs/images/                  ← 本页的插图
README.md · README.zh-CN.md · README.zh-TW.md
LICENSE                       ← AGPL-3.0
```

---

## 📜 许可证

Skill 本身（执行说明、参考文件和工具）采用 [GNU Affero General Public License v3.0](LICENSE) 授权。
`photographic-studio/assets/taste/` 中的示例照片版权归作者所有，**不在**此许可证范围内，未经许可请勿转载。

---

<p align="center">
  <sub>Photographic Studio v1.0.8 · 为非人像摄影而做 · 与 Claude 共同打造 · 代码与文档 AGPL-3.0 · 照片 © 作者本人</sub>
</p>
