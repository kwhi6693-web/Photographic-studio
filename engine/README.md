# Photographic Studio 引擎（engine/）

把 ChatGPT 里的修图流程（`photographic-studio/SKILL.md` v1.0.7）写成代码：**不依赖 ChatGPT**，一个命令修一张照片，或批量跑固定评测集；同一套代码就是将来 App 的后端核心。

## 现状（v0.1.0）

| 部分 | 状态 |
|---|---|
| 流程编排（测量 → 读片导演单 → G → 场景检查 → finish → G 被拦下重调一次 → settle → n_trim → 终检 → 回执） | 完成，离线测试通过 |
| 回放模式（用 ChatGPT 批次的 params.json + g.png 重跑） | 完成：重现了 ChatGPT 当时的路线 |
| 模型接口（OpenAI / Gemini，可替换） | 代码完成，**未在真实 API 上验证**（没有密钥） |
| 评测程序（固定照片集 × 多次，汇总耗时、路线、两次差别、对比图） | 完成 |
| HTTP 接口（提交、查询、取结果、删除；7 天自动删除） | 完成，原型级（单进程内存队列） |
| 还没做 | 构图重构（第 7 步，要看画面）；全分辨率输出；并行提速；真实 API 的耗时与成本 |

## 安装

```bash
cd engine
pip install -r requirements.txt
cp .env.example .env        # 以后把 API 密钥填进 .env；不填也能跑离线测试
python -m studio check      # 看当前用哪个模型、密钥是否已设（不显示密钥本身）
```

## 用法

```bash
python -m studio run 照片.jpg out/一张           # 修一张：out/一张/final.png + receipt.json
python -m studio eval 评测集/ out/评测 --runs=2  # 固定评测集，每张跑 2 次 → summary.md + sheets/
python -m studio serve --port=8000               # 给 App 用的 HTTP 接口
```

离线回放（不需要密钥）：`STUDIO_VISION=replay STUDIO_IMAGE=replay python -m studio run ../tests/fixtures/real_g/b1_03/original.jpeg out/回放`

## 换模型

**默认模型名是按 2026-11 的公开资料填的，开通账号后先在后台确认可用的模型 ID，不对就在 `.env` 里改。**

只改 `.env`：`STUDIO_VISION`、`STUDIO_IMAGE` 选厂商，`OPENAI_IMAGE_MODEL` 等选具体模型。新增厂商：在 `studio/providers/` 写一个有 `read()` 和 `edit()` 两个方法的类，在 `providers/__init__.py` 登记。

## 评测怎么看

`summary.md` 每行一张照片：路线、耗时、G 调用次数、两次成片的差别（0–255 的平均像素差）、成片检查结论。`sheets/` 里每张是 **原片 | 第 1 次 | 第 2 次**，打分只回答一件事：**每一次你都满意吗？**

“可以开始做 App”的标准（项目约定）：20 张评测集满意率 ≥ 90%，两次都满意；竞品盲比胜出；每张 ≤ 60 秒；单张成本已测清。

## 设计原则

- 判断（读片、导演单）交给视觉模型，光色方向交给 G，**所有像素操作都由 `photographic-studio/optional/` 里的确定性工具完成**，与 ChatGPT 里的 skill 是同一套代码、同一套规则。
- 密钥只放在 `.env` 或环境变量里，代码和回执都不记录密钥。
- 照片默认 7 天后删除（`STUDIO_KEEP_SECONDS`）。
