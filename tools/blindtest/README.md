# Blind test / 盲测回归工具

Same-position tap-to-toggle blind tests between two versions of the same photos, with identical-image sentinels,
an answer key kept out of the page, and an automatic merge-gate verdict. Used to check that a new version never
goes backwards against the current one.

同一位置点按切换的盲测工具：两个版本的同一张照片在原位切换比较，含同图哨兵；答案表不放进页面；自动计分并判定合并门槛。用来确认新版本不比现有版本倒退。

## 数据（不进仓库）/ Data (never committed)

```
blindtest_data/                  # listed in .gitignore
└── photos/
    ├── s1/  original.jpg  LR.jpg  v1.6.3.jpg  v2.0-rc1.jpg ...
    └── o2/  ...
```

每张照片一个文件夹，文件名就是版本名（`.jpg` / `.jpeg` / `.png` 都可以）。缺某个版本的照片会被跳过并列出原因。
One folder per photo; the file name (without extension) is the version name. Photos missing a version are skipped and listed.

## 用法 / Usage

**1. 出题 / Build a run**

```
python3 tools/blindtest/make_set.py --data blindtest_data --candidate v2.0-rc1 --baseline v1.6.3
```

| 选项 | 作用 |
|---|---|
| `--mode tone`（默认） | 自动对齐画框，两张都裁到公共区域，只比光色 |
| `--mode full` | 不对齐、不裁切，比整张画面（构图改动、人工精修）；两张放在原片比例的同一个框里居中显示 |
| `--ids s1,o2` | 只测指定照片（默认全部） |
| `--inline` | 另外为每批输出一个单文件 HTML（图片内嵌，长边 ≤ 1800 px，JPEG 90），可以直接发给朋友 |
| `--seed N` | 固定随机顺序，便于复现 |
| `--max-questions 10` | 每批题数上限（默认 10） |

每张照片出两题，左右对调，两题在同一批里且至少隔 4 题（8 题及以下的小批至少隔 3 题）。每批加 2 道同图哨兵。页面里不出现版本名，图片文件名是随机的；答案表写在运行目录的 `key.json`，作答前不要打开。

Each photo is shown twice with sides swapped, inside one batch, spread apart (≥ 4 questions in 10-question batches,
≥ 3 in smaller ones). Two identical-image sentinels per batch. Pages carry no version names; the key is in `key.json`.

**2. 作答 / Answer**

打开 `runs/<run>/batchN/page/index.html`（或单文件版）。点照片切换，两张都看过才能选。选了「图 1 / 图 2 更好」时，还要标「两张都能发」或「差的这张不想发」。做完复制结果。

**3. 计分 / Score**

```
python3 tools/blindtest/score.py --run blindtest_data/runs/<run> --answers batch1.txt batch2.txt ...
```

- 一批里任何一道哨兵没答「平」，整批作废，需要重做。
- 一张照片只有两题都选同一个版本才算胜，否则算平。
- **倒退**：基准版胜，且至少一题标了「差的这张不想发」。
- **合并门槛**：所有批次有效、没有倒退、候选胜的张数多于基准胜的张数。
- 退出码：0 通过，1 未通过，2 未完成（缺答案或有批次作废）。结果同时写入 `result.json`。

A batch counts only if both sentinels are answered as a tie. A photo is a win only when both answers agree.
Regression = baseline wins and at least one answer says the worse picture is not fine to post. Gate = all batches
valid, no regression, candidate wins > baseline wins. Exit code 0 pass, 1 fail, 2 incomplete.

## OpenCV

`tone` 模式对齐不同画框需要 OpenCV（`opencv-python-headless`）。没有 OpenCV 时，只接受同尺寸或同比例（会直接缩放，默认两者画框一致）的版本，其他照片会被跳过并提示；`full` 模式不受影响。
Aligning different frames in `tone` mode needs OpenCV. Without it, only versions with the same size or aspect are
accepted (same-aspect versions are resized and assumed to share the framing); `full` mode always works.
