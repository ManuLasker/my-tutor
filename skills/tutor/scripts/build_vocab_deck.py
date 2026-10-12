#!/usr/bin/env python3
"""Build a vocabulary practice topic (recognise + produce) from a book word list.

Source format (markdown), one entry per paragraph:
    **word** (optional note) — definition. Example: "Sentence from the book."

Generates <slug>/{meta.json, session.md, flashcards.json, cheatsheet.json,
exercises.json, exercises/, exam.json} and registers the slug in topics.json and
INDEX.md. Rebuilding an existing topic (--force) keeps progress.jsonl,
quiz-history.md, plan.md and everything in session.md from the
`<!-- tutor-notes -->` line on, and backs the old folder up first.

  python3 <skill>/scripts/build_vocab_deck.py --source ~/books/dune_volume_1_words.md \\
      --slug dune-vol1-vocab --group "English · Dune" \\
      --title "Volume 1" --order 1 --book "Dune Vol. 1" --dry-run

--dry-run writes to a temp dir and prints a report (entries missing an example,
words not found in their sentence). Fix those with --overrides, a JSON file:
    {"examples": {"word": "Practice sentence."}, "story_terms": ["Some Name"]}
Written examples are labelled "not from the book". Entries whose note contains
"story term" are recognise-only. The overrides file is copied into the topic
folder, and later rebuilds reuse it automatically.

Repeats across volumes: each deck records its words in vocab-words.json (with
the deck's creation time, kept across rebuilds). A word already owned by an
EARLIER vocab deck is left out of the new deck, listed in its cheat sheet, and
logged once as dont_know (source probe, task bNN-recognise) in the earlier
deck's progress.jsonl, so that volume shows up as needing retraining. Matching
is exact (case-insensitive headword); similar-looking words (spool / spooled)
are only reported. Force a match with overrides {"repeats": ["word"]}.
"""
import argparse, builtins, datetime, json, os, random, re, shutil, subprocess, sys, tarfile, tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_progress as lp  # noqa: E402  (shared TUTOR_HOME / config resolution)
from topics import write_atomic  # noqa: E402


def open(path, mode='r', **kw):  # noqa: A001  UTF-8 everywhere, whatever the OS locale
    if 'b' not in mode:
        kw.setdefault('encoding', 'utf-8')
    return builtins.open(path, mode, **kw)


# Data folder: TUTOR_HOME / config (VOCAB_LEARNING_ROOT still honoured); backups go next to it.
LEARNING = (os.path.realpath(os.path.expanduser(os.environ['VOCAB_LEARNING_ROOT']))
            if os.environ.get('VOCAB_LEARNING_ROOT') and not os.environ.get('TUTOR_HOME') else lp.ROOT)
BACKUPS = os.path.expanduser(os.environ.get('TUTOR_BACKUP_DIR') or os.environ.get('VOCAB_BACKUP_DIR')
                             or LEARNING.rstrip('/') + '-backups')
GENERATED = ['meta.json', 'session.md', 'flashcards.json', 'cheatsheet.json', 'exercises.json', 'exam.json', 'exercises',
             'vocab-words.json']
NOTES_MARKER = '<!-- tutor-notes -->'
SKIP_MASK ={'a', 'an', 'the', 'up', 'out', 'down', 'around', 'into', 'on', 'off', 'and', 'of', 'in', 'high'}


def parse(path):
    src = open(path).read()
    out = []
    for m in re.finditer(r'^\*\*(.+?)\*\*\s*(\([^)]*\))?\s*—\s*(.+)$', src, re.M):
        head, note, rest = m.group(1).strip(), (m.group(2) or '').strip(), m.group(3).strip()
        ex = re.search(r'Example:\s*["“](.+?)["”]\s*$', rest)
        out.append(dict(word=head, note=note, definition=(rest[:ex.start()] if ex else rest).strip(),
                        example=ex.group(1) if ex else None))
    return out


def stem(t):
    return t[:max(4, len(t) - 3)] if len(t) > 4 else t


def locate(word, sent):
    """Return (form, blanked, bolded) for word in sent, or None."""
    low, w = sent.lower(), word.lower()
    i = low.find(w)
    if i >= 0:
        j = i + len(w)
        while j < len(sent) and sent[j].isalpha():
            j += 1
        while i > 0 and sent[i - 1].isalpha():
            i -= 1
        f = sent[i:j]
        return f.lower(), sent[:i] + '____' + sent[j:], sent[:i] + f'**{f}**' + sent[j:]
    toks = w.split()
    m = re.search(r'\b' + r'\W+'.join(re.escape(stem(t)) + r'[a-z]*' for t in toks), sent, re.I)
    if m:
        f = m.group(0)
        return f.lower(), sent[:m.start()] + '____' + sent[m.end():], sent[:m.start()] + f'**{f}**' + sent[m.end():]
    if len(toks) == 2:  # split phrasal verb: "fended him off"
        m = re.search(r'\b(' + re.escape(stem(toks[0])) + r'[a-z]*)((?:\s+[\w\']+){1,3}?)\s+(' + re.escape(toks[1]) + r')\b', sent, re.I)
        if m:
            a, mid, b = m.group(1), m.group(2), m.group(3)
            pre, post = sent[:m.start()], sent[m.end():]
            return f'{a} {b}'.lower(), f'{pre}____{mid} ____{post}', f'{pre}**{a}**{mid} **{b}**{post}'
    return None


def mask(text, word):
    for t in word.lower().split():
        if t in SKIP_MASK:
            continue
        s = t[:max(3, len(t) - 3)] if len(t) > 4 else t
        text = re.sub(r'\b' + re.escape(s) + r'[a-z]*', '___', text, flags=re.I)
    return text


def key(word):
    return re.sub(r'\s+', ' ', word.strip().lower())


def looks_alike(x, y):
    """flinch / flinching, spool / spooled: the shorter word's stem starts the longer one."""
    short, long_ = sorted((x, y), key=len)
    s = stem(short)
    return len(s) >= 4 and long_.startswith(s)


def word_id(word):
    return 'word:' + re.sub(r'[^a-z0-9]+', '-', key(word)).strip('-')


def load_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def earlier_decks(slug, created):
    """word key -> {slug, title, group, task, word} for vocab decks created before this one."""
    prior = {}
    decks = []
    for s in load_json(os.path.join(LEARNING, 'topics.json'), []):
        vw = load_json(os.path.join(LEARNING, s, 'vocab-words.json'), None)
        if s != slug and vw and vw.get('created', '') < created:
            decks.append((vw['created'], s, vw))
    for _, s, vw in sorted(decks):  # oldest first: a word belongs to the first deck that had it
        for w in vw['words']:
            prior.setdefault(key(w['word']), {'slug': s, 'title': vw['title'], 'group': vw['group'],
                                              'task': f"b{w['batch']:02d}-recognise" if w['batch'] else 'story-terms',
                                              'word': w['word']})
    return prior


def first_sentence(d):
    m = re.match(r'(.+?\.)(\s|$)', d)
    return (m.group(1) if m else d).strip()


def build(a, out):
    rng = random.Random(1)
    ov = {'examples': {}, 'story_terms': []}
    if a.overrides:
        ov.update(json.load(open(a.overrides)))
    entries = parse(a.source)
    if not entries:
        sys.exit(f'no entries parsed from {a.source}')

    # Drop words already owned by an earlier deck (and duplicates inside this list).
    forced = {key(w) for w in ov.get('repeats', [])}
    repeats, similar, seen, kept = [], [], set(), []
    for e in entries:
        k = key(e['word'])
        if k in seen:
            similar.append(f"listed twice in this file: {e['word']!r} (second entry skipped)")
            continue
        seen.add(k)
        hit = a.prior.get(k)
        if not hit and k in forced:
            hit = next((v for pk, v in a.prior.items() if looks_alike(pk, k)), None)
        if hit:
            repeats.append(dict(hit, new_word=e['word']))
            continue
        near = [v['word'] for pk, v in a.prior.items() if looks_alike(pk, k)]
        if near:
            similar.append(f"{e['word']!r} looks like {near[0]!r} from {a.prior[key(near[0])]['title']} — kept (add to overrides 'repeats' if it's the same word)")
        kept.append(e)
    entries = kept

    words, problems = [], []
    for n, e in enumerate(entries, 1):
        w = dict(e, n=n, written=False,
                 story='story term' in e['note'].lower() or e['word'] in ov['story_terms'])
        if not w['example']:
            if e['word'] not in ov['examples']:
                problems.append(f"no example sentence: {e['word']!r} (add to overrides 'examples')")
                continue
            w['example'], w['written'] = ov['examples'][e['word']], True
        loc = locate(e['word'], w['example'])
        if not loc:
            problems.append(f"word not found in its sentence: {e['word']!r} — {w['example']!r}")
            continue
        w['form'], w['blank'], w['bold'] = loc
        words.append(w)
    if problems:
        print('PROBLEMS — fix with --overrides, nothing written:\n  ' + '\n  '.join(problems))
        sys.exit(2)

    practice = [w for w in words if not w['story']]
    if not practice:
        sys.exit('no new practice words left after removing repeats')
    batches = [practice[i:i + a.batch] for i in range(0, len(practice), a.batch)]
    for bi, b in enumerate(batches, 1):
        for w in b:
            w['batch'] = bi

    def bl(bi):
        b = batches[bi - 1]
        return f"Batch {bi:02d} · {b[0]['word']} → {b[-1]['word']}"

    def src_note(w):
        return '*(example written for practice — not from the book)*' if w['written'] else f'*— {a.book}*'

    def head(w):
        return f"**{w['word']}**" + (f" {w['note']}" if w['note'] else '')

    # Flashcards: per batch, recognise cards then produce cards; story terms last.
    cards = []
    for bi, b in enumerate(batches, 1):
        for w in b:
            cards.append({'q': f"🔎 **Recognise** · batch {bi:02d}\n\nWhat does **{w['word']}** mean here?\n\n> {w['bold']}",
                          'a': f"{head(w)} — {w['definition']}\n\n> {w['bold']}\n\n{src_note(w)}"})
        for w in b:
            cards.append({'q': f"✍️ **Produce** · batch {bi:02d}\n\nWhich word fills the blank?\n\n> {w['blank']}\n\n*Meaning:* {mask(first_sentence(w['definition']), w['word'])}",
                          'a': f"**{w['form']}**" + (f" (from *{w['word']}*)" if w['form'] != w['word'].lower() else '') +
                               f"\n\n> {w['bold']}\n\n{w['definition']}"})
    story = [w for w in words if w['story']]
    for w in story:
        cards.append({'q': f"🔎 **Recognise** · story term\n\nWhat is **{w['word']}** in the story?\n\n> {w['bold']}",
                      'a': f"{head(w)} — {w['definition']}\n\n{src_note(w)}"})

    cheat = [{'title': 'How to practise', 'content': (
        f"Source: `{a.source_display}` ({len(words)} entries, {len(practice)} practice words in {len(batches)} batches of {a.batch}).\n\n"
        "| Step | Skill | Where |\n|---|---|---|\n"
        "| 1 | **Recognise** — see the word, recall the meaning | 🔎 flashcards · Exam *recognise* matches |\n"
        "| 2 | **Produce** — see meaning/sentence, recall the word | ✍️ flashcards · Exercises (type the word) · Exam *produce* matches |\n\n"
        "Recognising is easier than producing: do 🔎 for a batch first, switch to ✍️ once the words feel familiar.")}]
    for bi, b in enumerate(batches, 1):
        cheat.append({'title': bl(bi), 'content': '\n\n'.join(
            f"{head(w)} — {w['definition']}\n> {w['bold']}" + (' ' + src_note(w) if w['written'] else '') for w in b)})
    if repeats:
        cheat.append({'title': 'Already in earlier volumes — retrain there', 'content': (
            "Not repeated in this deck. Each was logged as 🤷 *don't know* in the volume that first had it, "
            "so that volume's **Progress** shows it as a gap.\n\n| Word | First seen in | Batch |\n|---|---|---|\n" +
            '\n'.join(f"| **{r['new_word']}** | [{r['title']}](?topic={r['slug']}&mode=progress) | `{r['task']}` |" for r in repeats))})
    if story:
        cheat.append({'title': 'Story terms (not regular English words)', 'content': '\n\n'.join(
            f"{head(w)} — {w['definition']}\n> {w['bold']}" for w in story)})

    # Exercises: t1 = blanks + word bank (needs the right form), t2 = meanings only.
    exercises = []
    for bi, b in enumerate(batches, 1):
        d = f"{out}/exercises/batch-{bi:02d}"
        os.makedirs(d, exist_ok=True)
        t1 = '\n'.join(f"{i}. {w['blank']}" for i, w in enumerate(b, 1))
        t1 += '\n\nWord bank (change the form if needed, e.g. flinch → flinched):\n' + ', '.join(sorted(w['word'] for w in b)) + '\n'
        order = b[:]
        rng.shuffle(order)
        t2 = '\n'.join(f"{i}. {mask(first_sentence(w['definition']), w['word'])}" for i, w in enumerate(order, 1)) + '\n'
        open(f'{d}/t1.txt', 'w').write(t1)
        open(f'{d}/t2.txt', 'w').write(t2)
        exp1 = '\n'.join(w['form'] for w in b)
        exp2 = '\n'.join(w['word'].lower() for w in order)
        exercises.append({
            'id': f'batch-{bi:02d}', 'title': f"✍️ {bl(bi)}", 'difficulty': 'medium',
            'prompt': "Type **one answer per line**, in order, **lowercase**, no numbers.\n\n"
                      "- **t1** — fill each blank with the word *in the form the sentence needs* (word bank given).\n"
                      "- **t2** — no word bank: read the meaning, type the word in its **dictionary form** (as in the word bank).\n\n"
                      "Split phrases (e.g. *I ____ him ____*) → type both parts with one space: `fended off`.",
            'setup': 'Open the input (▸ Show input), write your answers in the box, then ▶ Check.',
            'tests': [{'input': f'exercises/batch-{bi:02d}/t1.txt', 'expected': exp1},
                      {'input': f'exercises/batch-{bi:02d}/t2.txt', 'expected': exp2}],
            'solution': f"t1:\n{exp1}\n\nt2:\n{exp2}",
            'explanation': '\n'.join(f"- **{w['word']}** — {first_sentence(w['definition'])}" for w in b),
            'hints': ['First letters, t1: ' + ' · '.join(w['form'][0] for w in b) + '  |  t2: ' + ' · '.join(w['word'][0].lower() for w in order),
                      'Lengths, t1: ' + ' · '.join(str(len(w['form'])) for w in b) + '  |  t2: ' + ' · '.join(str(len(w['word'])) for w in order),
                      'Check the ending the sentence needs: past tense (-ed), -ing, -ly adverb, or plural -s.'],
        })

    # Exam: per batch, groups of <=5 words → one recognise match + one produce match each.
    def groups(b):
        k = (len(b) + 4) // 5
        size = -(-len(b) // k)
        return [b[i:i + size] for i in range(0, len(b), size)]

    def distract(pool, exclude, n, key):
        cand = [w for w in pool if w not in exclude]
        rng.shuffle(cand)
        return [key(w) for w in cand[:n]]

    exam = []
    for bi, b in enumerate(batches, 1):
        others = [w for w in practice if w['batch'] != bi]
        for gi, g in enumerate(groups(b), 1):
            opts = [first_sentence(w['definition']) for w in g] + distract(others, g, 2, lambda w: first_sentence(w['definition']))
            perm = list(range(len(opts)))
            rng.shuffle(perm)
            shown = [opts[i] for i in perm]
            exam.append({'id': f'r{bi:02d}-{gi}', 'type': 'match', 'task': f'b{bi:02d}-recognise',
                         'question': 'Match each word (as used in the book sentence) to its meaning. Unmatched meanings are decoys.',
                         'prompts': [f"**{w['word']}** — “{w['example']}”" for w in g], 'options': shown,
                         'answer': [shown.index(first_sentence(w['definition'])) for w in g],
                         'explanation': '\n'.join(f"- **{w['word']}** — {w['definition']}" for w in g)})
            shown = [w['form'] for w in g] + distract(others, g, 2, lambda w: w['form'])
            rng.shuffle(shown)
            exam.append({'id': f'p{bi:02d}-{gi}', 'type': 'match', 'task': f'b{bi:02d}-produce',
                         'question': 'Fill each blank with the right word. Unmatched words are decoys.',
                         'prompts': [w['blank'] for w in g], 'options': shown,
                         'answer': [shown.index(w['form']) for w in g],
                         'explanation': '\n'.join(f"- {w['bold']} — *{first_sentence(w['definition'])}*" for w in g)})

    today = datetime.date.today().isoformat()
    session = (f"# {a.group} — {a.title} vocabulary\n\n"
               f"Generated {today} by `build_vocab_deck.py` from `{a.source_display}` (edit the word list there, then rebuild).\n\n"
               "Not a taught lesson — a **practice deck** for words met while reading.\n\n"
               f"- {len(words)} entries → {len(practice)} practice words in {len(batches)} batches of {a.batch} (book order)"
               + (f", plus {len(story)} story terms (recognise only)" if story else '') + ".\n"
               "- Two skills, practised in order per batch:\n"
               "  1. 🔎 **Recognise** — word + book sentence → meaning (flashcards, exam task `bNN-recognise`).\n"
               "  2. ✍️ **Produce** — blanked sentence / meaning → word (flashcards, Exercises tab, exam task `bNN-produce`).\n"
               + ''.join(f"- `{w['word']}` had no book sentence; a practice sentence was written and is marked as such.\n" for w in words if w['written'])
               + (f"- {len(repeats)} words were already in earlier volumes — left out here, logged as don't know there: "
                  + ', '.join(f"{r['new_word']} ({r['title']})" for r in repeats) + ".\n" if repeats else '')
               + f"- Progress: `python3 <skill>/scripts/log_progress.py --topic {a.slug} --task b03-produce --result correct|wrong|dont_know --question \"...\"`.\n\n"
               "## Batches\n\n" + '\n'.join(f"- **{bi:02d}** — " + ', '.join(w['word'] for w in b) for bi, b in enumerate(batches, 1)) + '\n')

    meta = {'title': a.title, 'group': a.group, 'order': a.order}
    os.makedirs(out, exist_ok=True)
    for name, obj in [('meta.json', meta), ('flashcards.json', cards), ('cheatsheet.json', cheat),
                      ('exercises.json', exercises), ('exam.json', exam)]:
        with open(f'{out}/{name}', 'w') as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
    open(f'{out}/session.md', 'w').write(session)
    with open(f'{out}/vocab-words.json', 'w') as f:
        json.dump({'created': a.created, 'slug': a.slug, 'title': a.title, 'group': a.group,
                   'words': [{'word': w['word'], 'batch': w.get('batch')} for w in words],
                   'repeats': [{'word': r['new_word'], 'from': r['slug'], 'task': r['task'], 'logged': False} for r in repeats]},
                  f, indent=2, ensure_ascii=False)
    if a.overrides:
        shutil.copy(a.overrides, f'{out}/vocab-overrides.json')
    return dict(entries=len(words), practice=len(practice), story=len(story), batches=len(batches),
                cards=len(cards), exercises=len(exercises), exam=len(exam), written=[w['word'] for w in words if w['written']],
                repeats=[f"{r['new_word']} → {r['slug']} {r['task']}" for r in repeats], similar=similar)


def log_repeats(a, dest, old):
    """Log each repeat once as dont_know in the earlier deck; remember it in vocab-words.json."""
    done = {key(r['word']) for r in (old or {}).get('repeats', []) if r.get('logged')}
    vw = json.load(open(f'{dest}/vocab-words.json'))
    for r in vw['repeats']:
        if key(r['word']) in done:
            r['logged'] = True
            continue
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log_progress.py'), '--topic', r['from'], '--task', r['task'],
               '--result', 'dont_know', '--source', 'probe', '--qid', word_id(r['word']), '--run', f'repeat-{a.slug}',
               '--question', f"Didn't know “{r['word']}” again — met it in {a.title}",
               '--note', f"Not repeated in {a.slug}; retrain it here."]
        res = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, 'TUTOR_HOME': LEARNING})
        r['logged'] = res.returncode == 0
        print(('logged' if r['logged'] else 'LOG FAILED') + f": {r['word']} → {r['from']} {r['task']}" +
              ('' if r['logged'] else f" ({res.stderr.strip()})"))
    with open(f'{dest}/vocab-words.json', 'w') as f:
        json.dump(vw, f, indent=2, ensure_ascii=False)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', required=True, help='markdown word list')
    p.add_argument('--slug', required=True, help='topic folder name, e.g. dune-vol2-vocab')
    p.add_argument('--group', required=True, help='topic-picker group, e.g. "English · <Book>"')
    p.add_argument('--title', required=True, help='topic title inside the group, e.g. "Volume 2"')
    p.add_argument('--order', type=int, default=1, help='position inside the group')
    p.add_argument('--book', default='the book', help='short label for example sentences, e.g. "Dune Vol. 2"')
    p.add_argument('--batch', type=int, default=10, help='words per batch (default 10)')
    p.add_argument('--overrides', help='JSON {"examples": {...}, "story_terms": [...]}')
    p.add_argument('--dry-run', action='store_true', help='build into a temp dir and report; touch nothing')
    p.add_argument('--force', action='store_true', help='rebuild an existing topic (keeps progress, backs up first)')
    a = p.parse_args()

    a.source = os.path.expanduser(a.source)
    a.source_display = a.source.replace(os.path.expanduser('~'), '~', 1)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', a.slug):
        sys.exit('slug must be lowercase letters, digits and dashes')
    dest = os.path.join(LEARNING, a.slug)
    old_vw = load_json(f'{dest}/vocab-words.json', None)
    a.created = (old_vw or {}).get('created') or datetime.datetime.now().isoformat(timespec='seconds')
    a.prior = earlier_decks(a.slug, a.created)
    if not a.overrides and os.path.exists(f'{dest}/vocab-overrides.json'):
        a.overrides = f'{dest}/vocab-overrides.json'
    elif a.overrides:
        a.overrides = os.path.expanduser(a.overrides)

    if a.dry_run:
        out = os.path.join(tempfile.mkdtemp(prefix='vocab-'), a.slug)
        print(json.dumps(build(a, out), ensure_ascii=False))
        print(f'dry run OK — preview in {out}')
        return

    if os.path.exists(dest) and not a.force:
        sys.exit(f'{dest} exists — use --force to rebuild (progress is kept)')

    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(BACKUPS, exist_ok=True)
    if os.path.exists(dest):
        with tarfile.open(f'{BACKUPS}/{a.slug}-{ts}.tar.gz', 'w:gz') as t:
            t.add(dest, arcname=a.slug)
        print(f'backup: {BACKUPS}/{a.slug}-{ts}.tar.gz')

    stage = os.path.join(tempfile.mkdtemp(prefix='vocab-'), a.slug)
    stats = build(a, stage)  # build fully before touching the real folder
    os.makedirs(dest, exist_ok=True)
    # the tutor's lesson notes live below NOTES_MARKER in session.md — carry them over
    old_session = f'{dest}/session.md'
    if os.path.exists(old_session):
        old = open(old_session).read()
        if NOTES_MARKER in old:
            with open(f'{stage}/session.md', 'a') as f:
                f.write('\n' + old[old.index(NOTES_MARKER):])
    for name in GENERATED + ['vocab-overrides.json']:
        target = os.path.join(dest, name)
        if os.path.exists(os.path.join(stage, name)):
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.move(os.path.join(stage, name), target)

    tp = os.path.join(LEARNING, 'topics.json')
    topics = load_json(tp, [])
    if a.slug not in topics:
        if os.path.exists(tp):
            shutil.copy(tp, f'{BACKUPS}/topics-{ts}.json')
        topics.append(a.slug)
        write_atomic(tp, json.dumps(sorted(set(topics))) + '\n')

    ip = os.path.join(LEARNING, 'INDEX.md')
    line = (f"- [{a.group} — {a.title}](./{a.slug}/session.md) — vocab practice deck (recognise + produce), "
            f"{stats['practice']} words in {stats['batches']} batches — built {datetime.date.today().isoformat()}")
    lines = (open(ip).read() if os.path.exists(ip) else '# Learning Index\n\n## Topics\n').rstrip('\n').split('\n')
    hit = [i for i, l in enumerate(lines) if f'(./{a.slug}/session.md)' in l]
    if os.path.exists(ip):
        shutil.copy(ip, f'{BACKUPS}/INDEX-{ts}.md')
    if hit:
        lines[hit[0]] = line
    else:
        lines.append(line)
    entries = sorted((l for l in lines if l.startswith('- [')), key=str.lower)
    head = [l for l in lines if not l.startswith('- [')]
    write_atomic(ip, '\n'.join(head + entries) + '\n')

    log_repeats(a, dest, old_vw)
    print(json.dumps(stats, ensure_ascii=False))
    print(f'installed → {dest}')


if __name__ == '__main__':
    main()
