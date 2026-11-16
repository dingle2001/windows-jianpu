"""Regression for native long-rest anchoring and export calibration."""
import argparse
import tempfile
from pathlib import Path

import pymupdf

from audit import audit_project
from converter import convert, write_draft
from jpword_layout import MM_PER_PT, REST_MARK, apply_row_gap, move_attached_text, replace_page_breaks, text_line
from jpword_pdf import export_preview, fit_exported_rests, inspect_export
from score_io import load_score, part_measures, source_rows


SOURCE = """<score-partwise>
  <part-list><score-part id="P1"><part-name>Flute</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
      <time><beats>2</beats><beat-type>4</beat-type></time>
      <measure-style><multiple-rest>2</multiple-rest></measure-style></attributes>
      <note><rest measure="yes"/><duration>2</duration></note>
    </measure>
    <measure number="2"><note><rest measure="yes"/><duration>2</duration></note></measure>
    <measure number="3"><print new-system="yes"/>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>"""

TEMPLATE = """.Title
Intro = {empty}
Title = {empty}
SubTitle = {empty}
KeyAndMeters = {empty}
WordsByAndMusicBy = {empty}
.Options
VertSpacing = 1.00, 0.30, 0.20, 5.50
.Voice
""".format(empty="")


def draw_outline(pdf, center):
    """Draw the native profile's filled vector shapes at known positions."""
    with pymupdf.open() as doc:
        page = doc.new_page(width=595.28, height=841.89)
        for top in (100, 180):
            page.draw_rect((200,top,200.7,top+17.856),color=None,fill=(0,0,0))
        a, b = center-20, center+20
        outline = page.new_shape()
        outline.draw_polyline([(a,100),(a+1.5,100),(a+1.5,105),(b-1.5,105),
            (b-1.5,100),(b,100),(b,113),(b-1.5,113),(b-1.5,107),
            (a+1.5,107),(a+1.5,113),(a,113),(a,100)])
        outline.finish(color=None, fill=(0,0,0))
        outline.commit()
        doc.save(pdf)


def verify(work):
    source = work / "rests.musicxml"
    template = work / "template.jpwabc"
    project = work / "draft.jpwabc"
    source.write_text(SOURCE,encoding="utf-8")
    template.write_text(TEMPLATE,encoding="utf-16")
    draft, report = convert(source,template,row_gap_mm=15.)
    write_draft(project,draft)
    marker = REST_MARK.search(draft)
    assert marker and tuple(marker.group(i) for i in (1,2,6)) == ("1","1","2")
    assert "0-{C:0,None}" in draft
    assert "VertSpacing = 1.00, 0.30, 0.20, 15.00" in draft
    assert report["row_gap_mm"] == 15
    assert audit_project(source,project)["marks"]["multirest"] == 1

    paged, report = convert(source,template,page_starts=[3])
    assert report["explicit_pages"] == 2
    paged_file = work / "paged.jpwabc"
    rows = source_rows(part_measures(load_score(source)))
    new_pages = [(1,rows[0][1]),(2,rows[1][1])]
    assert replace_page_breaks(paged,rows) == convert(source,template)[0]
    assert replace_page_breaks(convert(source,template)[0],new_pages) == paged
    write_draft(paged_file,replace_page_breaks(draft,new_pages))
    assert audit_project(source,paged_file,page_starts=[3])["explicit_pages"] == 2
    label = text_line(2,1,0,-6.4,"Allegro")
    updated, xy = move_attached_text(draft+"\n"+label,2,1,"Allegro",3,-4)
    assert xy == (3,-10.4) and "Text@2,1(3.00,-10.40)" in updated
    assert "0.20, 17.00" in apply_row_gap(updated,17)

    missed, aligned = work/"missed.pdf", work/"aligned.pdf"
    center = (20/MM_PER_PT+200)/2
    # A 2.4 mm shift in a wide cell must still be reported.
    shift_pt = 2.4/MM_PER_PT
    draw_outline(missed,center+shift_pt)
    draw_outline(aligned,center)
    report = inspect_export(missed,source)
    assert [issue["issue"] for issue in report["issues"]] == ["rest_needs_fit"], report
    assert report["minimum_system_separation_mm"] == round(80*MM_PER_PT,2)
    fitted, changes = fit_exported_rests(project,report)
    assert len(changes) == 1 and abs(changes[0]["offset_delta_mm"] + 2.4) < .01, changes
    assert changes[0]["anchor_delta"] == -1.0
    assert abs(float(REST_MARK.search(fitted)[3])-float(marker[3])+1) < .01
    corrected = work / "corrected.jpwabc"
    write_draft(corrected,fitted)
    assert audit_project(source,corrected)["marks"]["multirest"] == 1
    assert inspect_export(aligned,source)["status"] == "pdf_layout_checked"
    assert export_preview(aligned,1,72).startswith(b"\x89PNG\r\n\x1a\n")
    print("JPword layout calibration checked: rest anchor, offsets, page breaks and export preview.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job",type=Path)
    with tempfile.TemporaryDirectory(prefix="jpword-layout-",dir=parser.parse_args().job) as directory:
        verify(Path(directory))
