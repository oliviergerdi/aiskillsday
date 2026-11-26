"""Stylesheet-text checks for the <=760px layout of finding rows (UX-4)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_REL = "app/web/static/nparity.css"
MEDIA = "@media (max-width: 760px)"


def _split(css):
    """Return (mobile block body, css with the whole block removed)."""
    start = css.index(MEDIA)
    open_ = css.index("{", start)
    depth, i = 0, open_
    while True:
        depth += css[i] == "{"
        depth -= css[i] == "}"
        if depth == 0:
            break
        i += 1
    return css[open_ + 1 : i], css[:start] + css[i + 1 :]


def _rules():
    body = _split((ROOT / CSS_REL).read_text())[0]
    return [
        ([s.strip() for s in sel.split(",")], decl)
        for sel, decl in re.findall(r"([^{}]+)\{([^}]*)\}", body)
    ]


def _decls(selector_test, prop_value):
    """Declaration blocks of rules with any selector passing selector_test and containing prop_value."""
    return [
        d
        for sels, d in _rules()
        if any(selector_test(s) for s in sels) and re.search(prop_value, d)
    ]


def _col2(cls):
    return _decls(lambda s: s.endswith(cls), r"grid-column:\s*2\b")


def test_mobile_summary_children_stacked_in_column_2():
    for cls in (".f-path", ".f-kind", ".pbar", ".f-reason"):
        assert _col2(cls), f"{cls} has no grid-column: 2 rule in mobile block"
    assert ":nth-child" not in _split((ROOT / CSS_REL).read_text())[0]


def test_mobile_arrow_stays_beside_endpoint():
    assert _decls(lambda s: s.endswith("summary"), r"grid-template-columns:\s*14px 1fr")
    col1 = r"grid-column:\s*1\b"
    assert not _decls(lambda s: s.endswith((".f-ep", "summary")), col1)
    assert _col2(".f-path"), ".f-path could land in the 14px marker column"


def test_mobile_static_rows_stacked():
    assert _decls(lambda s: s.endswith(".f-static"), r"grid-template-columns:\s*14px 1fr")
    assert _decls(lambda s: ".f-static" in s and s.endswith(".f-path"), r"grid-column:\s*2\b")
    assert _decls(
        lambda s: ".f-static" in s and s.endswith(".f-kind"),
        r"grid-column:\s*2\s*!important",
    )
    assert _decls(lambda s: ".f-static" in s and "span" in s, r"display:\s*none")


def test_rules_outside_mobile_block_unchanged():
    base = subprocess.run(
        ["git", "merge-base", "main", "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    main = subprocess.run(
        ["git", "show", f"{base}:{CSS_REL}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert _split((ROOT / CSS_REL).read_text())[1] == _split(main)[1]
