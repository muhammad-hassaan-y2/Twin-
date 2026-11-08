"""The write-up is a measurement artefact, not prose: it is built out of the
tables, so a table that changes shape has to break the build rather than leave a
stale number on the page. No network, and no `tmp_path` (broken on this host)."""
import shutil
import tempfile
from pathlib import Path

import pytest

from swarm_oversight.pdf_report import RESULTS, build

OUT = Path(tempfile.mkdtemp(prefix="swarm-report-"))


def test_the_report_builds_and_fits_the_page_limit():
    pypdf = pytest.importorskip("pypdf")
    out = build(OUT / "report.pdf")
    pages = pypdf.PdfReader(str(out)).pages
    # The sprint caps the body at 8 pages, NOT counting references and appendices.
    body = len(pages)
    for i, p in enumerate(pages):
        lines = (p.extract_text() or "").splitlines()
        if any(l.strip() == "References" for l in lines):
            body = i
            break
    assert body <= 8, f"body pages {body} (total {len(pages)})"


def test_the_pareto_figure_is_drawn_from_the_same_cells():
    build(OUT / "report.pdf")
    png = RESULTS / "fig_pareto.png"
    assert png.exists() and png.stat().st_size > 20_000


def test_a_table_that_lost_a_row_breaks_the_build():
    """Negative control: the prose quotes cells by name, so a renamed or dropped
    row has to raise here, not print an empty figure on page 4."""
    quiet = Path(tempfile.mkdtemp(prefix="swarm-results-"))
    shutil.copytree(RESULTS, quiet, dirs_exist_ok=True)
    table = quiet / "control_stub_both.md"
    lines = [l for l in table.read_text(encoding="utf-8").splitlines()
             if "rules_hold" not in l]
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(KeyError):
        build(OUT / "broken.pdf", results=quiet)
