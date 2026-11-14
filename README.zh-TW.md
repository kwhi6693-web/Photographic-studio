<p align="center">
  <img src="docs/images/banner.zh-TW.svg" alt="Photographic Studio — 一句「修」，一張成片" width="100%">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <b>繁體中文</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.8-c8963e?style=flat-square" alt="version 1.0.8">
  <img src="https://img.shields.io/badge/engine-2.1.0%20prototype-3a5ba8?style=flat-square" alt="engine 2.1.0">
  <img src="https://img.shields.io/badge/Agent%20Skill-SKILL.md-1d2f63?style=flat-square" alt="Agent Skill">
  <img src="https://img.shields.io/badge/非人像-建築·街景·風光·夜景·展品-3a5ba8?style=flat-square" alt="非人像">
  <img src="https://img.shields.io/badge/python-numpy·Pillow·OpenCV-2b3a55?style=flat-square" alt="numpy Pillow OpenCV">
  <img src="https://img.shields.io/badge/license-MIT-c8963e?style=flat-square" alt="MIT">
</p>

<p align="center">
  <b>發一張照片，說一個字：「修」。</b><br>
  它會像一位後期攝影師那樣先讀懂這張照片，再交給你一張——<br>
  <b>看得出提升、仍然是你拍的那一刻、光線講得通、看不出 AI 痕跡</b>——的成片。
</p>

---

## 🎞️ 前後對比

> 左為原片，右為成片。照片都是作者自己拍的，成片經作者親自挑選認可。

<table>
  <tr>
    <td width="50%"><img src="photographic-studio/assets/taste/02_night_before_after.jpg" alt="夜色中的塔與倒影"><br><sub><b>夜色中的塔與倒影</b> · 保住夜空的黑，讓塔、橋和倒影的燈更清楚</sub></td>
    <td width="50%"><img src="photographic-studio/assets/taste/03_canal_before_after.jpg" alt="運河與雲"><br><sub><b>運河與雲</b> · 天空有了顏色和體積，樹從死黑裡透出層次</sub></td>
  </tr>
  <tr>
    <td><img src="photographic-studio/assets/taste/05_bronze_ox_before_after.jpg" alt="錯金銀銅牛燈"><br><sub><b>錯金銀銅牛燈</b> · 銅色、綠鏽、赭紅分明，黑牆依舊乾淨</sub></td>
    <td><img src="photographic-studio/assets/taste/06_blue_vase_museum_before_after.jpg" alt="藍釉金彩瓶"><br><sub><b>藍釉金彩瓶</b> · 鈷藍更濃、金飾更亮，展櫃的暗一點不提</sub></td>
  </tr>
  <tr>
    <td><img src="photographic-studio/assets/taste/01_building_before_after.jpg" alt="鐵塔框景裡的鐘樓"><br><sub><b>鐵塔框景裡的鐘樓</b> · 夕陽的暖與鋼架的冷拉開</sub></td>
    <td><img src="photographic-studio/assets/taste/04_willow_lake_before_after.jpg" alt="垂柳與湖"><br><sub><b>垂柳與湖</b> · 剋制的清透，晴日裡的安靜</sub></td>
  </tr>
</table>

---

## 🎬 它怎麼修一張照片

<p align="center">
  <img src="docs/images/pipeline.zh-TW.svg" alt="讀片 → 導演單 → 只借光與色 → 精修與檢查 → 一張成片" width="100%">
</p>

**1 · 讀片**　先回答“這張照片在講什麼”：故事、情緒、主角、風格方向；再看光從哪來、顏色怎麼搭、空間怎麼分層。

**2 · 導演單**　把判斷寫成六行後期方案，例如：

```text
故事｜風格：暗展櫃中，藍釉與金飾承接展燈｜低調博物館靜物，深藍與暖金分明
主角：中央藍釉瓶；怎麼突出：放大已有受光面的體積與金飾反差，背景保持深暗
影調：黑場保留，高光輕壓，主體中間調展開，局部反差增加
色彩：鈷藍與暖金為主，加強釉色與金飾，收斂臺座偏色
不能動：瓶形、紋樣、頂珠、展簽、玻璃裡的真實反光
構圖：保持——線圖、瓶子與右側映像共同交代展陳
```

**3 · 只借 AI 的光與色**　讓宿主的影像模型出一版，但**只拿走它的光線和色彩**，成片的每一個畫素仍然來自原片——文字、人物、紋理都是你拍到的那些。

**4 · 精修與檢查**　確定性調色工具按導演單補齊，再過兩道關：

- **物理關**：加亮只落在原本有光的地方；不給展品憑空加光圈，也不把真實的光斑、釉光抹掉；明暗次序、天空漸變、倒影都要講得通。
- **力度關**：看得出提升，又不過頭；博物館展品按主角來判斷。

不合格？它會自己換一級更穩的做法重來，直到交出一張合格的成片——**不停下來問你**。

**5 · 一張成片**　只交一張圖，配一行 `故事｜風格`。

---

## 🧭 它堅持的四件事

| | |
|:--:|---|
| 🔆 | **表現力第一**——“改了等於沒改”算失敗。 |
| 📷 | **還是你拍的那一刻**——同一場景、同一時刻、同一視角。 |
| 🕯️ | **光要講得通**——放大照片裡本來就有的光，不畫現實中不存在的光。 |
| 🍃 | **看不出 AI**——沒有磨皮感、塑膠感、假細節、假 HDR。 |

---

## 🚀 開始使用

**作為 Agent Skill 安裝**：把 [`photographic-studio/`](photographic-studio) 整個目錄安裝到支援 `SKILL.md` 的宿主，然後：

```text
（發一張照片）修
```

**不能安裝的宿主**：把目錄打包成 zip，作為附件發過去，說一句：

```text
按附件裡的 Photographic Studio 處理這張照片
```

### 口令

| 你說 | 它做 |
|---|---|
| `修` | 讀片 → 導演單 → 出片 → 檢查 → 交一張成片 |
| `精修` | 多出幾個方向，比較後挑最好的一張（更慢） |
| `太暖了` · `再通透一點` | 按你的話改導演單重做，並記住這條口味 |
| `看回執` | 導演單、提示詞、參數、檢查結論 |
| `看標記表` | 每張照片的處理標記彙總 |

### 能力分級

它會先看宿主有什麼工具，再決定怎麼做：

| 級別 | 宿主能力 | 出片方式 |
|:--:|---|---|
| **T1** | 有影像編輯模型，也能執行 Python | 原片畫素 + AI 光色 → 精修 |
| **T2** | 只能執行 Python | 確定性調色直出 |
| **T3** | 只有影像編輯模型 | 直接用模型的結果，並如實說明 |
| **T4** | 都沒有 | 給出讀片與後期建議 |

---

## 🏗️ 架構

<p align="center">
  <img src="docs/images/architecture.zh-TW.svg" alt="兩個入口——ChatGPT skill 和引擎——共用一套確定性工具" width="100%">
</p>

兩個入口，**同一套規則**。兩邊都呼叫 `photographic-studio/optional/` 裡的同一套確定性工具，所以每次改進兩邊同時生效，測試也同時涵蓋兩邊。

| | ChatGPT 版（`photographic-studio/`） | 引擎（`engine/`） |
|---|---|---|
| 狀態 | 日常在用 | 原型，等 API 金鑰 |
| 誰來執行步驟 | GPT 讀 `SKILL.md` 自己執行 | 程式 |
| G（光色模型） | 宿主內建的圖像工具 | 圖像編輯 API（OpenAI / Gemini，在 `config.toml` 裡設定） |
| 適合 | 現在修圖 | 批次評測、全尺寸輸出、未來 App 的後端 |
| 目標耗時 | — | 每張 ≤ 2 分鐘 |

API 金鑰特意留空：設定環境變數 `OPENAI_API_KEY` / `GEMINI_API_KEY`，或填進 `engine/config.toml`（不會上傳到 GitHub）。詳見 [`engine/README.md`](engine/README.md)。

## 🗂️ 倉庫結構

```text
photographic-studio/          ← Skill 本體（安裝這個目錄）
├── SKILL.md                  ← 執行說明，入口
├── references/               ← 總則、讀片與處方、六類題材、導演單、物理、力度、交付……
│   └── genres/               ← 建築 · 街景 · 風光 · 夜景 · 室內 · 靜物與展品
├── optional/                 ← 工具（numpy · Pillow · OpenCV）
│   ├── finish.py             ← 一步出片，含自動重做階梯
│   ├── look_transfer.py      ← 原片畫素 + AI 光色
│   ├── grade.py              ← 按導演單調色
│   ├── settle.py             ← 一次完成力度校準
│   ├── full_res.py           ← 把修圖帶回原圖尺寸
│   ├── physics_check.py      ← 自然光物理檢查
│   └── intensity_check.py    ← 力度檢查
├── assets/taste/             ← 口味參照：作者認可的前後對比
├── CHANGELOG.md
└── SHA256SUMS.txt
engine/                       ← 流程寫成程式（原型）
├── studio_engine/            ← 流程 · 模型介面 · 評測 · 命令列
├── service/app.py            ← 給未來 App 用的 HTTP 介面
└── config.example.toml       ← 模型和金鑰（複製為 config.toml）
tests/                        ← 測試與真實照片樣例（每次提交自動跑）
docs/images/                  ← 本頁的插圖
README.md · README.zh-CN.md · README.zh-TW.md
LICENSE                       ← MIT
```

---

## 📜 授權條款

Skill 本身（執行說明、參考檔案和工具）採用 [MIT 授權條款](LICENSE)（2026-11-14 起；此前的版本為 AGPL-3.0）。
示例與測試照片（`photographic-studio/assets/`、`tests/fixtures/`、`docs/images/`）版權歸作者所有，**不在**此授權範圍內，未經許可請勿轉載。

---

<p align="center">
  <sub>Photographic Studio v1.0.8 · 為非人像攝影而做 · 與 Claude 共同打造 · 程式碼與文件 MIT · 照片 © 作者本人</sub>
</p>
