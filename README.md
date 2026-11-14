<p align="center">
  <img src="docs/images/banner.svg" alt="Photographic Studio — Send a photo. Say “fix”. Get one finished photo." width="100%">
</p>

<p align="center">
  <b>English</b> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.8-c8963e?style=flat-square" alt="version 1.0.8">
  <img src="https://img.shields.io/badge/engine-2.1.0%20prototype-3a5ba8?style=flat-square" alt="engine 2.1.0">
  <img src="https://img.shields.io/badge/Agent%20Skill-SKILL.md-1d2f63?style=flat-square" alt="Agent Skill">
  <img src="https://img.shields.io/badge/non--portrait-architecture·street·landscape·night·museum-3a5ba8?style=flat-square" alt="non-portrait">
  <img src="https://img.shields.io/badge/python-numpy·Pillow·OpenCV-2b3a55?style=flat-square" alt="numpy Pillow OpenCV">
  <img src="https://img.shields.io/badge/license-MIT-c8963e?style=flat-square" alt="MIT">
</p>

<p align="center">
  <b>Send a photo. Say one word: “fix” (or 「修」).</b><br>
  Like a seasoned retoucher, it first reads what your photo is about — then hands you back one finished image<br>
  that <b>clearly looks better, is still the moment you captured, has light that makes sense, and shows no trace of AI</b>.
</p>

---

## ⚡ Start in 30 seconds

1. Download the [`photographic-studio/`](photographic-studio) folder.
2. In an LLM agent with image generation (one that can see photos and edit them with its own image model), install it — or zip it and attach it to a new chat.
3. Send a photo and say **fix**. You get one finished photo back. No settings, no API key.

Everything below explains what it does, how, and the second, developer-only way to run it.

---

## 🎯 What problem it solves

For people who **love taking photos but don't want to spend time on post-processing**.

- Doing it yourself (Lightroom and the like) takes skill and time for every photo.
- One-tap enhance buttons either change almost nothing, or over-process: plastic textures, fake HDR, invented light, details the camera never saw.

Photographic Studio sits in between: **one word, one finished photo**. It reads the photo first, then edits it so that it is clearly better, still the moment you captured (every pixel comes from your original), with light that obeys real physics, and no AI look. Architecture, street, landscape, night, interiors, still life and museum pieces — **not portraits**.

---

## 🎞️ Before &amp; after

> Left: original. Right: finished. All photos were taken by the author; every result here was picked and approved by the author.

<table>
  <tr>
    <td width="50%"><img src="photographic-studio/assets/taste/02_night_before_after.jpg" alt="Tower and reflection at night"><br><sub><b>Tower and reflection at night</b> · the night sky stays black; the tower, bridge and reflections glow clearer</sub></td>
    <td width="50%"><img src="photographic-studio/assets/taste/03_canal_before_after.jpg" alt="Canal and clouds"><br><sub><b>Canal and clouds</b> · the sky gains colour and volume; trees emerge from the blacks</sub></td>
  </tr>
  <tr>
    <td><img src="photographic-studio/assets/taste/05_bronze_ox_before_after.jpg" alt="Inlaid bronze ox lamp"><br><sub><b>Inlaid bronze ox lamp</b> · bronze, green patina and red inlay come apart; the black wall stays clean</sub></td>
    <td><img src="photographic-studio/assets/taste/06_blue_vase_museum_before_after.jpg" alt="Cobalt-and-gold vase"><br><sub><b>Cobalt-and-gold vase</b> · deeper cobalt, brighter gold — and not a lumen added to the dark showcase</sub></td>
  </tr>
  <tr>
    <td><img src="photographic-studio/assets/taste/01_building_before_after.jpg" alt="Clock tower framed by steel"><br><sub><b>Clock tower framed by steel</b> · warm sunset against cool steel</sub></td>
    <td><img src="photographic-studio/assets/taste/04_willow_lake_before_after.jpg" alt="Willows over a lake"><br><sub><b>Willows over a lake</b> · restrained clarity, the quiet of a clear day</sub></td>
  </tr>
</table>

---

## 📖 Words used on this page

| Word | Meaning |
|---|---|
| **Skill** | the `photographic-studio/` folder: instructions plus tools that an AI agent follows |
| **Agent / host** | the AI app you chat with. It must be an **LLM agent with image generation**: it can look at a photo and edit it with its own image model |
| **G** | the image model of your agent (or of an API). It makes a draft; **only its light and colour are used** |
| **N** | this project's own tools: fixed rules, no AI; they make the actual finished photo from your original's pixels |
| **Director's brief** | six lines the agent writes after reading the photo: story, subject, tone, colour, what must not change, crop |
| **Label** | how a photo was made: `original pixels + G light & colour → N refine` (normal) · `N direct` (no usable G draft, N only) · `G + detail restore` (rare upgrade route) |
| **Receipt** | the record of one photo: brief, prompt, parameters, check results. Hidden unless you say `show receipt` |
| **Capability tiers** | what the skill does when your agent can't edit images or run Python (T1–T4, below) |
| **Engine** | the same pipeline as a Python program, using model APIs with your own key (developers) |
| **Replay** | an engine test mode that answers from recorded real runs instead of calling a paid model |
| **Route** | which step of the automatic retry ladder produced the photo, e.g. `default`, `museum_strength` (stronger subject for museum pieces), `n_direct` |

---

## 🔁 Input &amp; output

**In a chat (the skill)** — input: one photo and one word. Output: one finished photo, one line of story and style, and a label saying how it was made. Two real deliveries from the test runs:

```text
you:  (photo of a vine under a skylight)  修
it:   (finished photo)
      Story: a dead vine casts crossing shadows under a geometric skylight | Style: quiet modern interior, vine shadows in dialogue with the architecture
      original pixels + G light & colour → N refine
```

```text
you:  (photo of red maples against a grey garden wall)  修
it:   (finished photo)
      Story: red maples and tile shadows on an old wall in clear weather | Style: crisp garden architecture, grey brick behind red leaves
      N direct          ← the image model darkened the sky twice, both drafts were rejected, so only deterministic grading was used
```

**On the command line (the engine, prototype)** — input: a photo file. Output: a folder with `final.png` (or `final_full.jpg` for photos larger than the working size), `receipt.json` with every step, its time and the estimated model cost, plus the intermediate files. A real run, replaying a recorded museum photo:

```text
$ python -m studio_engine.cli run original.jpeg out/
{ "status": "done", "final": "out/final.png", "route": "museum_strength", "seconds": 66.7, "cost_usd": 0.0 }
steps: measure 1.3 s · brief · G · finish 26.0 s · settle 33.4 s · n_trim 0.3 s
```

(`cost_usd` is 0 here because the replay provider makes no paid call; with a real model API the receipt shows the estimate.)

---

## 🎬 How it edits a photo

<p align="center">
  <img src="docs/images/pipeline.svg" alt="Read → Director's brief → Light & colour → Refine & check → One photo" width="100%">
</p>

**1 · Read the photo**　First it answers *what is this photo about?* — story, mood, subject, style. Then: where the light comes from, how the colours work, how space is layered.

**2 · Write a director's brief**　Six lines of post-production intent, for example:

```text
Story | style : a dark showcase; cobalt glaze and gold catch the exhibit light | low-key museum still life
Subject       : the cobalt vase — amplify the lit volume and the gold relief; keep the background dark
Tone          : keep the blacks, ease the highlights, open the subject's midtones, more local contrast
Colour        : cobalt and warm gold lead; richer glaze and gilding; calm the plinth's colour cast
Do not touch  : shape, patterns, finial, label, the real reflections in the glass
Composition   : keep — the line drawing, the vase and the reflection tell the exhibition together
```

**3 · Borrow only AI's light &amp; colour**　Your agent's image model (G) makes a version, but **only its light and colour are taken**. Every pixel of the result still comes from your original — the text, the people, the textures are the ones you actually captured.

**4 · Refine and check**　The project's deterministic tools (N) finish the brief, then the image has to pass two gates:

- **Physics** — brightening only lands where light already falls; no invented halos around an exhibit, no real highlights or glaze sheen wiped away; tonal order, sky gradients and reflections all have to make sense.
- **Strength** — visibly better, never overdone; museum pieces are judged on the subject itself.

Not good enough? It quietly retries a safer step on its own until a result passes — **it never stops to ask you**.

**5 · One photo**　You get exactly one image, with a single line: `story | style`.

---

## 🧭 Four things it never compromises on

| | |
|:--:|---|
| 🔆 | **Expression first** — an edit nobody can see counts as a failure. |
| 📷 | **Still your moment** — same scene, same time, same viewpoint. |
| 🕯️ | **Light that makes sense** — amplify the light already in the photo; never paint light that couldn't exist. |
| 🍃 | **No AI look** — nothing waxy or plastic, no fake detail, no fake HDR. |

---

## 🚀 Installation

There are **two separate ways** to use Photographic Studio. They are different downloads, with different requirements. Most people want option 1.

| | Option 1 · Skill | Option 2 · Engine |
|---|---|---|
| What you download | the `photographic-studio/` folder | the whole repository (the `engine/` folder plus the skill's tools) |
| Who it is for | anyone with an LLM agent with image generation | developers; the future app's back end |
| API key | **not needed** | **needed** — your own OpenAI or Gemini key |
| Who pays for the AI | your agent subscription, as usual | you, per use, on your own API account |
| Where your photos go | to your agent, as in any chat | to the model provider you configure |
| Status | in daily use | prototype; not yet run against a live API |

The skill package has no place for an API key and does not contain the engine. The engine does not need an agent.

### Option 1 · Skill (no API key)

**What you need**: an **LLM agent with image generation** — it can look at a photo and edit it with its own image model. For the full result it should also be able to run Python; see *Capability tiers* below for what happens when it can't.

**Steps**

1. Download the [`photographic-studio/`](photographic-studio) folder (or a release zip of it).
2. If your agent supports installing skills (`SKILL.md`), install the folder.
   If it doesn't — or you'd rather not install — zip the folder, attach it in a new conversation and say:
   ```text
   Process this photo with the attached Photographic Studio
   ```
3. Send a photo and say:
   ```text
   fix
   ```

Tested so far on image2.6 (phone and web apps); agents that support `SKILL.md` can use it.

### Option 2 · Engine (your own API key)

**What you need**: Python 3.11 or newer; an API key from OpenAI or Google Gemini; the names of the models you want (check the provider's current model list). One model reads the photo and writes the brief; one edits images (G). They can come from the same provider.

**Steps**

1. Get the repository and install the dependencies:
   ```bash
   git clone https://github.com/kwhi6693-web/Photographic-studio.git
   cd Photographic-studio
   pip install -r engine/requirements.txt
   ```
2. Create your configuration and fill in the two model names (`[vision]` and `[editor]`):
   ```bash
   cp engine/config.example.toml engine/config.toml
   ```
   `engine/config.toml` is git-ignored, so it is never uploaded.
3. Provide the key — preferably as an environment variable (or as `api_key` in `config.toml`):
   ```bash
   export OPENAI_API_KEY=...        # or GEMINI_API_KEY=...
   ```
4. Check, then make one small real call to each model:
   ```bash
   cd engine
   python -m studio_engine.cli selftest           # what is configured; no paid call
   python -m studio_engine.cli selftest --live    # one tiny real call per model
   ```

**Good to know**

- Without a key nothing is called: `selftest` reports *NOT CONFIGURED*, and a run stops with *not configured* instead of failing halfway.
- Switching provider or model means editing `config.toml` only (`provider = "openai" | "gemini"`, `model = ...`); no code change.
- Cost: every run writes an estimated cost in `receipt.json`, from the `price_per_call_usd` values in `config.toml`. Your provider's bill is what counts. Use a key made only for this project, with a monthly spending limit, and revoke it when you stop testing.
- Privacy: in this mode your photos are sent to the model provider you configured, under that provider's terms.
- Status: the engine has been tested offline by replaying recorded real runs; it has not yet been run against a live model API.

---

## 🕹️ Usage

### In a chat (the skill)

| You say | It does |
|---|---|
| `fix` · `修` | read → brief → edit → check → one finished photo |
| `fine-tune` · `精修` | explores several directions and keeps the best (slower) |
| `too warm` · `a bit clearer` | rewrites the brief and redoes it; notes the taste for this conversation |
| `show receipt` · `看回执` | brief, prompt, parameters, check results |
| `show flag log` · `看标记表` | a running log of flags across photos |

### On the command line (the engine)

| Command | Does |
|---|---|
| `python -m studio_engine.cli run PHOTO OUT_DIR` | one photo → `OUT_DIR/final.png` + `receipt.json` |
| `python -m studio_engine.eval SET_DIR OUT_DIR --runs=2` | every photo in a folder, N times each → comparison sheets + `summary.md` (finish rate, time, cost, run-to-run difference, runs over 2 minutes) |
| `uvicorn service.app:app` | HTTP API for the future app: upload, poll, download, delete (prototype: no accounts or payments) |

### Capability tiers

It looks at what the host can do first, then decides how to work:

| Tier | Host can… | How the photo is made |
|:--:|---|---|
| **T1** | edit images with a model **and** run Python | original pixels + AI light &amp; colour → refine |
| **T2** | run Python only | deterministic grading |
| **T3** | edit images with a model only | the model's edit, honestly labelled |
| **T4** | neither | a reading of the photo and editing advice |

---

## ❓ Questions first-time users ask

**Does it cost anything?** The skill is free (MIT). It runs on your agent, so you need whatever plan your agent requires for image editing. The engine uses your own API key; you pay your provider per use.

**Do I need an API key?** Not for the skill. Only for the engine.

**Can I use it on my phone?** Yes — the skill was developed and tested on image2.6 in an iPhone app.

**How long does one photo take?** In the agent app, measured: about 3–4 minutes per photo, one after another for a batch. The engine's target is 2 minutes or less per photo.

**Can I send several photos at once?** Yes. It edits them one by one and delivers one finished photo each.

**Will it retouch portraits?** No. People as the main subject are out of scope.

**Will it change what is in my photo?** No objects are added or removed, the framing stays (at most a light straighten or crop that keeps at least 80 % of the frame), and every pixel comes from your original.

**What if I don't like the result?** Say what's wrong in a few words (`too warm`, `a bit clearer`): it rewrites the brief and redoes the photo.

**Where do my photos go?** With the skill: to your agent, as in any chat. With the engine: to the model provider you configured, under its terms.

---

## 🏗️ Architecture

<p align="center">
  <img src="docs/images/architecture.svg" alt="Two entry points — the skill (in an LLM agent with image generation) and the engine — share one set of deterministic tools" width="100%">
</p>

Two ways in, **one set of rules**. Both call the same deterministic tools in `photographic-studio/optional/`, so every improvement reaches both, and the tests cover both.

| | Skill in an LLM agent with image generation (`photographic-studio/`) | Engine (`engine/`) |
|---|---|---|
| Status | in daily use | prototype, waiting for an API key |
| Who runs the steps | the agent, reading `SKILL.md` | code |
| G (light & colour model) | the host's built-in image tool | an image-editing API (OpenAI / Gemini, set in `config.toml`) |
| Good for | editing photos today | batch evaluation, full-resolution output, the future app's back end |
| Target time | — | ≤ 2 minutes per photo |

API keys are left empty on purpose: set `OPENAI_API_KEY` / `GEMINI_API_KEY` or fill `engine/config.toml` (git-ignored). Details in [`engine/README.md`](engine/README.md).

## 🗂️ Repository layout

```text
photographic-studio/          ← the skill itself (install this folder)
├── SKILL.md                  ← entry point and instructions
├── references/               ← principles, reading & prescriptions, genres, brief, physics, strength, delivery…
│   └── genres/               ← architecture · street · landscape · night · interior · still life & museum
├── optional/                 ← tools (numpy · Pillow · OpenCV)
│   ├── finish.py             ← one-step edit with an automatic retry ladder
│   ├── look_transfer.py      ← original pixels + AI light & colour
│   ├── grade.py              ← grading by the director's brief
│   ├── settle.py             ← strength calibration in one call
│   ├── full_res.py           ← carries an edit back to full resolution
│   ├── physics_check.py      ← natural-light physics check
│   └── intensity_check.py    ← strength check
├── assets/taste/             ← taste references: before/after pairs approved by the author
├── CHANGELOG.md
└── SHA256SUMS.txt
engine/                       ← the pipeline as code (prototype)
├── studio_engine/            ← pipeline · model providers · evaluation · CLI
├── service/app.py            ← HTTP API for the future app
└── config.example.toml       ← models and keys (copy to config.toml)
tests/                        ← tests + real photo fixtures (GitHub Actions on every commit)
docs/images/                  ← illustrations for this page
README.md · README.zh-CN.md · README.zh-TW.md
LICENSE                       ← MIT
```

> The skill's own instructions and references are written in Chinese; any capable agent can follow them.

---

## 📜 License

The skill — instructions, references and tools — is licensed under the [MIT License](LICENSE) (since 2026-11-14; earlier versions were AGPL-3.0).
The example and test photographs (`photographic-studio/assets/`, `tests/fixtures/`, `docs/images/`) are © the author and are **not** covered by this license; please do not reuse them without permission.

---

<p align="center">
  <sub>Photographic Studio v1.0.8 · made for non-portrait photography · built together with Claude · code &amp; docs MIT · photos © the author</sub>
</p>
