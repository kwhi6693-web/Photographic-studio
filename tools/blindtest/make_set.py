#!/usr/bin/env python3
"""Photographic Studio blind test - build one run of same-position tap-to-toggle comparisons.

Data layout (private, never committed - see .gitignore):
  DATA/photos/<id>/<version>.jpg|jpeg|png     e.g. photos/s1/original.jpg, photos/s1/LR.jpg, photos/s1/v1.6.3.jpg

Usage:
  python3 tools/blindtest/make_set.py --data blindtest_data --candidate v2.0-rc1 --baseline v1.6.3 [--ids all|s1,o2]
                                      [--mode tone|full] [--inline] [--seed N] [--out DIR]

Every photo becomes one pair shown twice, sides swapped, both inside the same batch and spread apart
(>= 4 questions apart in 10-question batches, >= 3 in smaller ones). Each batch has 2 identical-image sentinels and at
most --max-questions questions (default 10), so 14 photos become 4 short batches. Pages carry no version names;
the answer key is written to OUT/key.json and is read only by score.py.

  --mode tone   (default) align the two versions and cut both to their shared frame: compares light and colour only.
  --mode full   no alignment, no cutting: compares whole pictures (composition changes, hand edits). Both sit in a
                box with the original's aspect (or the baseline's if there is no original), centred, never enlarged
                beyond the box.
  --inline      also write one self-contained HTML per batch (images embedded, long edge <= 1800 px, JPEG 90)
                that can be sent to a friend as a single file.
"""
import argparse, base64, datetime, io, json, math, random, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bt_align  # noqa: E402

EXTS = ('.jpg', '.jpeg', '.png')
INLINE_LONG_EDGE = 1800
INLINE_QUALITY = 90


def find_version(photo_dir, version):
    for p in sorted(photo_dir.iterdir()):
        if p.suffix.lower() in EXTS and p.name[:-len(p.suffix)] == version:
            return p
    return None


def plan_batches(ids, max_q, rng):
    per = max(1, (max_q - 2) // 2)          # photos per batch: 2 questions each + 2 sentinels
    ids = list(ids)
    rng.shuffle(ids)
    nb = math.ceil(len(ids) / per)
    base, extra = divmod(len(ids), nb)
    out, k = [], 0
    for b in range(nb):
        n = base + (1 if b < extra else 0)
        out.append(ids[k:k + n])
        k += n
    return out


def order_batch(photos, rng, tries=200000):
    """Return (items, gap): items are (photo, kind, swap) with kind 'pair' | 'sent_c' | 'sent_b'."""
    items = []
    for p in photos:
        first = rng.random() < 0.5
        items += [(p, 'pair', first), (p, 'pair', not first)]
    sent = rng.sample(photos, 2) if len(photos) >= 2 else [photos[0], photos[0]]
    items += [(sent[0], 'sent_c', False), (sent[1], 'sent_b', False)]
    want = 4 if len(items) >= 10 else 3
    for gap in range(want, 0, -1):
        for _ in range(tries):
            rng.shuffle(items)
            if items[0][1] != 'pair':
                continue
            pos = {}
            for i, (p, kind, _) in enumerate(items):
                if kind == 'pair':
                    pos.setdefault(p, []).append(i)
            if all(v[1] - v[0] >= gap for v in pos.values()):
                return list(items), gap
    raise RuntimeError('could not order the batch')


def encode(img, long_edge, quality=90):
    img = bt_align.fit_long_edge(img, long_edge)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    return buf.getvalue(), img.size


def write_page(path, title, qs, images, hint):
    tpl = (HERE / 'page_template.html').read_text(encoding='utf-8')
    html = (tpl.replace('__TITLE__', title).replace('__HINT__', hint)
               .replace('__IMG__', json.dumps(images)).replace('__QS__', json.dumps(qs, ensure_ascii=False)))
    path.write_text(html, encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', required=True)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--ids', default='all')
    ap.add_argument('--mode', choices=('tone', 'full'), default='tone')
    ap.add_argument('--out')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--max-questions', type=int, default=10)
    ap.add_argument('--long-edge', type=int, default=1600, help='long edge of the page pictures (px)')
    ap.add_argument('--inline', action='store_true')
    ap.add_argument('--force', action='store_true', help='overwrite an existing run directory')
    a = ap.parse_args(argv)

    if a.candidate == a.baseline:
        sys.exit('--candidate and --baseline must be different versions')
    if a.max_questions < 4:
        sys.exit('--max-questions must be at least 4 (one pair twice + two sentinels)')
    data = Path(a.data)
    photos_dir = data / 'photos'
    if not photos_dir.is_dir():
        sys.exit(f'no photos folder: {photos_dir}')
    wanted = sorted(p.name for p in photos_dir.iterdir() if p.is_dir()) if a.ids == 'all' else a.ids.split(',')
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(1 << 30)
    rng = random.Random(seed)

    # load and frame every usable photo
    framed, skipped, align_info = {}, {}, {}
    for pid in wanted:
        d = photos_dir / pid
        if not d.is_dir():
            skipped[pid] = 'no such photo folder'
            continue
        fc, fb = find_version(d, a.candidate), find_version(d, a.baseline)
        if fc is None or fb is None:
            skipped[pid] = 'missing ' + ' and '.join(v for v, f in ((a.candidate, fc), (a.baseline, fb)) if f is None)
            continue
        cand, base = bt_align.load(fc), bt_align.load(fb)
        try:
            b_out, c_out, info = bt_align.same_frame(base, cand, a.mode)   # baseline is the reference frame
        except bt_align.AlignError as e:
            skipped[pid] = str(e)
            continue
        if a.mode == 'full':
            fo = find_version(d, 'original')
            ref = bt_align.load(fo) if fo else base
            box = (ref.shape[1], ref.shape[0])
        else:
            box = (b_out.shape[1], b_out.shape[0])
        framed[pid] = {'c': bt_align.to_image(c_out), 'b': bt_align.to_image(b_out), 'box': box}
        align_info[pid] = info
    if not framed:
        sys.exit('nothing to compare: ' + json.dumps(skipped, ensure_ascii=False))

    stamp = datetime.date.today().isoformat()
    out = Path(a.out) if a.out else data / 'runs' / f'{stamp}_{a.candidate}-vs-{a.baseline}_{a.mode}'
    if out.exists() and any(out.iterdir()):
        if not a.force:
            sys.exit(f'{out} already exists; use --force or another --out')
        for old in out.glob('batch*'):          # only what an earlier run of this tool wrote
            if old.is_dir():
                shutil.rmtree(old)
        for name in ('key.json', 'result.json'):
            (out / name).unlink(missing_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    key = {'candidate': a.candidate, 'baseline': a.baseline, 'mode': a.mode, 'seed': seed,
           'created': datetime.datetime.now().isoformat(timespec='seconds'),
           'photos': sorted(framed), 'skipped': skipped, 'align': align_info, 'batches': []}
    hint = '' if a.mode == 'tone' else '两张放在同一个框里居中显示，比例不同时会留边。'
    for bn, photos in enumerate(plan_batches(sorted(framed), a.max_questions, rng), 1):
        items, gap = order_batch(photos, rng)
        bdir = out / f'batch{bn}'
        (bdir / 'page' / 'img').mkdir(parents=True, exist_ok=True)
        qs, kq, used = [], [], {}
        for k, (pid, kind, swap) in enumerate(items, 1):
            qid = f'{bn}-{k:02d}'
            f = framed[pid]
            if kind == 'pair':
                sides = ('b', 'c') if swap else ('c', 'b')
            else:
                sides = ('c', 'c') if kind == 'sent_c' else ('b', 'b')
            q = {'q': qid, 'ar': f"{f['box'][0]} / {f['box'][1]}"}
            for slot, side in zip(('a', 'b'), sides):
                if (pid, side) not in used:          # each picture is stored once, under a random name
                    used[(pid, side)] = '%08x' % rng.getrandbits(32)
                q[slot] = used[(pid, side)]
            qs.append(q)
            ver = {'c': a.candidate, 'b': a.baseline}
            kq.append({'q': qid, 'photo': pid, 'kind': 'pair' if kind == 'pair' else 'sentinel',
                       'img1': ver[sides[0]], 'img2': ver[sides[1]]})
        files, inline = {}, {}
        for (pid, side), tok in used.items():
            blob, _ = encode(framed[pid][side], a.long_edge)
            (bdir / 'page' / 'img' / f'{tok}.jpg').write_bytes(blob)
            files[tok] = f'img/{tok}.jpg'
            if a.inline:
                small, _ = encode(framed[pid][side], min(a.long_edge, INLINE_LONG_EDGE), quality=INLINE_QUALITY)
                inline[tok] = 'data:image/jpeg;base64,' + base64.b64encode(small).decode()
        title = f'盲选 第 {bn} 批'
        write_page(bdir / 'page' / 'index.html', title, qs, files, hint)
        if a.inline:
            write_page(bdir / f'batch{bn}_inline.html', title, qs, inline, hint)
        key['batches'].append({'batch': bn, 'photos': photos, 'mirror_gap': gap, 'questions': kq})
    (out / 'key.json').write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'run: {out}')
    for b in key['batches']:
        print(f"  batch {b['batch']}: {len(b['questions'])} questions, {len(b['photos'])} photos, "
              f"mirror gap >= {b['mirror_gap']}  ->  {out / ('batch%d' % b['batch']) / 'page' / 'index.html'}")
    for pid, why in skipped.items():
        print(f'  skipped {pid}: {why}')
    for pid, info in align_info.items():
        if 'warning' in info:
            print(f"  note {pid}: {info['warning']}")
    print('answer key: key.json (do not open it before answering)')
    return out


if __name__ == '__main__':
    main()
