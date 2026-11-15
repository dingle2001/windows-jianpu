"""Automated output checks for the original engraving fixture."""
import argparse
import json
from pathlib import Path
import re

import pymupdf


def pdf_page(path):
    with pymupdf.open(path) as document:
        assert len(document) == 1, path
        page = document[0]
        assert page.get_contents() and abs(page.rect.width - 595.28) < 2, path
        return page.get_text()


def verify(job):
    edition = job / "edition-01"
    proof = pdf_page(edition / "alignment.insitu.pdf")
    final = pdf_page(edition / "numbered.jianpu.pdf")
    for output in (proof, final):
        assert "Windows Etude" in output.replace("\xa0", " "), output
        assert re.search(r"1\s*=\s*G", output), output
        assert re.search(r"=\s*84", output), output
    assert "Flute" in proof and "test score" in proof, proof
    assert "4/4" in final and "test score" not in final, final
    with (edition / "alignment.insitu.report.json").open(encoding="utf-8") as handle:
        report = json.load(handle)
    assert report["staff_count"] == report["rendered_staff_count"] == 2, report
    assert report["incomplete_staff_count"] == report["alignment_mismatch_count"] == 0, report
    print("PDF checks passed: one A4 page per output, 2/2 aligned systems; pure key, meter and tempo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    verify(parser.parse_args().job)
