"""Exercise JPword score data without publishing a private engraving template."""
import argparse
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from audit import audit_project
from converter import convert, write_draft


def verify(job):
    with tempfile.TemporaryDirectory(prefix="jpword-test-", dir=job) as directory:
        work = Path(directory)
        source = work / "ornaments.musicxml"
        template = work / "test-header.jpwabc"
        output = work / "proof.jpwabc"
        tree = ET.parse(job / "reviewed.musicxml")
        notes = tree.getroot().findall("part/measure/note")
        for note, family, name in (
            (notes[0], "articulations", "staccato"),
            (notes[1], "ornaments", "trill-mark"),
        ):
            notations = note.find("notations")
            if notations is None:
                notations = ET.SubElement(note, "notations")
            ET.SubElement(ET.SubElement(notations, family), name)
        tree.write(source, encoding="utf-8", xml_declaration=True)
        template.write_text(
            ".Title\nIntro = \nTitle = \nSubTitle = \n"
            "KeyAndMeters = \nWordsByAndMusicBy = \n.Voice\n",
            encoding="utf-16",
        )
        draft, report = convert(source, template)
        write_draft(output, draft)
        assert "KeyAndMeters = {1=G,4/4}" in draft, draft
        assert "{J=84}" in draft, draft
        assert [row["visible_measures"] for row in report["layout"]] == [4, 4], report
        result = audit_project(source, output)
        assert result["marks"] == {"DunYin": 1, "ChanYin": 1, "pitched_events": 30}, result
    print("JPword score data checked: two systems, key, tempo, staccato and native trill anchors.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    verify(parser.parse_args().job)
