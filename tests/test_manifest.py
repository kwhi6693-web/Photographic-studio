"""The package's own hash list must describe the package: what is installed is what was approved."""
import hashlib
from conftest import PKG


def entries():
    return dict(reversed(line.split(None, 1)) for line in (PKG / 'SHA256SUMS.txt').read_text().splitlines() if line.strip())


def test_every_listed_file_matches():
    bad = [n for n, h in entries().items() if hashlib.sha256((PKG / n.strip()).read_bytes()).hexdigest() != h]
    assert not bad


def test_every_package_file_is_listed():
    listed = {n.strip() for n in entries()}
    actual = {p.relative_to(PKG).as_posix() for p in PKG.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt' and '__pycache__' not in p.parts}
    assert actual == listed
