#!/usr/bin/env python3
"""Photographic Studio blind test - score one run against its answer key.

Usage:
  python3 tools/blindtest/score.py --run RUN_DIR --answers answers.txt [more.txt ...]
  (answers may also be piped on stdin; lines that are not answers are ignored)

Answer lines are what the page prints, e.g.
  1-03 2 都能发 清透        question 1-03: picture 2 is better, both are fine to post, word "清透"
  1-07 1 不想发 假          picture 1 is better, the worse one is not fine to post
  1-05 平 一致              no visible difference

Rules
- A batch counts only when every question in it is answered and both sentinels (identical pictures) are answered 平.
  A missed sentinel voids the whole batch: redo it.
- A photo is a win for one version only when both of its questions pick that version; anything else is a tie.
- Regression: the baseline wins a photo AND at least one of the two answers says the worse picture is not fine to post.
- Merge gate (candidate may replace baseline): every batch valid, no regression, and candidate wins > baseline wins.
Exit code: 0 gate passed, 1 gate failed, 2 incomplete (missing answers or a voided batch).
"""
import argparse, json, re, sys
from pathlib import Path

LINE = re.compile(r'^\s*(\d+)-(\d+)\s+(1|2|平)(?:\s+(两张都能发|都能发|差的这张不想发|不想发))?(?:\s+(.*?))?\s*$')


def parse(text):
    out = {}
    for raw in text.splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        b, k, choice, flag, word = m.groups()
        qid = f'{int(b)}-{int(k):02d}'
        usable = None if flag is None else (flag in ('都能发', '两张都能发'))
        out[qid] = {'choice': choice, 'usable': usable, 'word': (word or '').strip(' -') or None}
    return out


def score(key, answers):
    cand, base = key['candidate'], key['baseline']
    batches, photos = [], {}
    for b in key['batches']:
        qs = b['questions']
        got = [q for q in qs if q['q'] in answers]
        st = {'batch': b['batch'], 'photos': b['photos'], 'answered': len(got), 'questions': len(qs)}
        if not got:
            st['status'] = 'not answered'
        elif len(got) < len(qs):
            st['status'] = 'incomplete'
            st['missing'] = [q['q'] for q in qs if q['q'] not in answers]
        else:
            bad = [q['q'] for q in qs if q['kind'] == 'sentinel' and answers[q['q']]['choice'] != '平']
            st['status'] = 'void' if bad else 'valid'
            if bad:
                st['failed_sentinels'] = bad
        batches.append(st)
        if st['status'] != 'valid':
            continue
        for q in qs:
            if q['kind'] != 'pair':
                continue
            a = answers[q['q']]
            winner = None if a['choice'] == '平' else (q['img1'] if a['choice'] == '1' else q['img2'])
            p = photos.setdefault(q['photo'], {'answers': [], 'words': []})
            p['answers'].append({'q': q['q'], 'winner': winner, 'usable': a['usable']})
            if a['word']:
                p['words'].append(a['word'])

    wins_c = wins_b = ties = 0
    regressions = []
    for pid, p in sorted(photos.items()):
        w = [x['winner'] for x in p['answers']]
        not_ok = any(x['usable'] is False for x in p['answers'])
        if w[0] is not None and w[0] == w[1]:
            p['verdict'] = 'candidate' if w[0] == cand else 'baseline'
        elif None not in w:
            p['verdict'] = 'tie (split)'      # each answer picked a different version
        else:
            p['verdict'] = 'tie'
        p['not_fine_to_post'] = not_ok
        if p['verdict'] == 'candidate':
            wins_c += 1
        elif p['verdict'] == 'baseline':
            wins_b += 1
            if not_ok:
                p['regression'] = True
                regressions.append(pid)
        else:
            ties += 1

    complete = all(b['status'] == 'valid' for b in batches)
    reasons = []
    if not complete:
        reasons.append('有批次未答完或已作废')
    if regressions:
        reasons.append('倒退：' + '、'.join(regressions))
    if wins_c <= wins_b:
        reasons.append(f'没有净胜（候选 {wins_c} : 基准 {wins_b}）')
    gate = 'incomplete' if not complete else ('pass' if not reasons else 'fail')
    return {'candidate': cand, 'baseline': base, 'mode': key.get('mode'), 'batches': batches, 'photos': photos,
            'totals': {'candidate_wins': wins_c, 'baseline_wins': wins_b, 'ties': ties},
            'regressions': regressions, 'gate': gate, 'reasons': reasons}


VERDICT_ZH = {'candidate': '候选胜', 'baseline': '基准胜', 'tie': '平', 'tie (split)': '平（两次不一致）'}
STATUS_ZH = {'valid': '有效', 'void': '作废（哨兵未过）', 'incomplete': '未答完', 'not answered': '未作答'}


def report(r):
    lines = [f"候选 {r['candidate']}  对  基准 {r['baseline']}（{r['mode']} 模式）", '']
    for b in r['batches']:
        extra = ''
        if b.get('failed_sentinels'):
            extra = '，未过哨兵：' + ', '.join(b['failed_sentinels'])
        if b.get('missing'):
            extra = '，缺：' + ', '.join(b['missing'])
        lines.append(f"第 {b['batch']} 批：{STATUS_ZH[b['status']]}（{b['answered']}/{b['questions']} 题{extra}）")
    lines.append('')
    for pid, p in sorted(r['photos'].items()):
        tag = '  ← 倒退' if p.get('regression') else ('  （有「不想发」）' if p['not_fine_to_post'] else '')
        words = '、'.join(p['words'])
        lines.append(f"{pid:8s} {VERDICT_ZH[p['verdict']]}{tag}" + (f'   {words}' if words else ''))
    t = r['totals']
    lines += ['', f"合计：候选胜 {t['candidate_wins']}，基准胜 {t['baseline_wins']}，平 {t['ties']}"]
    gate = {'pass': '通过', 'fail': '未通过', 'incomplete': '未完成'}[r['gate']]
    lines.append(f'合并门槛：{gate}' + ('（' + '；'.join(r['reasons']) + '）' if r['reasons'] else ''))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--answers', nargs='*', default=[])
    a = ap.parse_args(argv)
    run = Path(a.run)
    key = json.loads((run / 'key.json').read_text(encoding='utf-8'))
    text = '\n'.join(Path(f).read_text(encoding='utf-8') for f in a.answers) if a.answers else sys.stdin.read()
    r = score(key, parse(text))
    (run / 'result.json').write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
    print(report(r))
    return {'pass': 0, 'fail': 1, 'incomplete': 2}[r['gate']]


if __name__ == '__main__':
    sys.exit(main())
