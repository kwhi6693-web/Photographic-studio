"""Every sample image the references describe must be in the package, and every image in the package must be described
(a sample nobody explains teaches the judging model nothing)."""
import re
from conftest import PKG


def check(doc, folder):
    text = (PKG / 'references' / doc).read_text(encoding='utf-8')
    named = set(re.findall(r'`([\w]+_before_(?:after|bad)\.jpg)`', text))
    present = {p.name for p in (PKG / 'assets' / folder).glob('*.jpg')}
    assert named == present, (named - present, present - named)


def test_taste_samples_match_profile():
    check('taste_profile.md', 'taste')


def test_counter_examples_match_doc():
    check('counter_examples.md', 'counter')
