# Photographic Studio engine (v2.1.0)

The retouching pipeline as code. Same rules and the same deterministic tools as the ChatGPT skill
(`photographic-studio/optional/*.py` stay the single source of truth), but the steps are run by code and the two
judgement calls go to model APIs:

| Step | Who | Notes |
|---|---|---|
| measure | `measure.py` | numbers only |
| read + director brief | vision model API | JSON, clamped to safe ranges (`prompts.py`) |
| portrait? | code | stops with status `unsupported` |
| G | image-editing API | prompt from the brief + physics sentences; scene check; one retry |
| finish | `finish.py` | route ladder, physics + strength checks |
| G rejected → second G | code | names the problems in the prompt (v1.0.7) |
| settle | `settle.py` | strength calibration + anchoring (`--n-direct` when G was not used) |
| n_trim | `n_trim.py` | clipping guard |
| full resolution | `full_res.py` | when the photo is larger than `work_size`: the edit is carried back to the original size, detail from the original |

Every run writes `receipt.json` (steps, seconds, model calls, estimated cost) next to `final.png`.

## Setup

```
pip install -r engine/requirements.txt
cp engine/config.example.toml engine/config.toml      # git-ignored
# put the model names in config.toml; put keys in the environment (preferred) or config.toml:
export OPENAI_API_KEY=...        # and/or GEMINI_API_KEY=...
cd engine && python -m studio_engine.cli selftest          # what is configured (no paid call)
python -m studio_engine.cli selftest --live                # one small real call per model
```

Switching provider or model = editing `config.toml` (`provider = "openai" | "gemini" | "replay"`, `model = ...`).
No code change. Use a project-only key with a spending limit, and revoke it when testing is over.

## Use

```
python -m studio_engine.cli run photo.jpg out/                       # one photo
python -m studio_engine.eval eval_set/ results/ --runs=2             # the fixed evaluation set, each photo twice
uvicorn service.app:app                                              # HTTP service for the app (prototype)
```

`results/sheets/*.jpg` show original | run 1 | run 2 for scoring; `results/summary.md` has finish rate, seconds,
cost and run-to-run difference.

## Offline / tests

`provider = "replay"` answers from a recorded run folder (`params.json`, `g.png`, `receipt.json`), so the whole
pipeline runs without network. `tests/test_engine.py` replays real ChatGPT runs and checks the engine takes the
same routes.

## Not done yet (by design, waiting for the API key or the app phase)

- Live calls are untested until a key is configured; `selftest --live` is the first thing to run.
- Speed (replay, CPU, no model latency): finish ≈ 25–30 s + settle ≈ 25–33 s per photo, plus the model calls.
  The 60 s target needs the model calls to stay under ~10 s in total, or finish to get faster.
- HEIC/HEIF uploads need `pillow-heif` installed.
- Crop/straighten (`reframe.py`) is not decided by the engine yet; the brief has no crop field.
- Service: single process, in-memory queue, local disk, no accounts or payments.
