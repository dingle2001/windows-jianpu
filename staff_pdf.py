"""Optional source PDF checks for the Finale-style vector profile used on Qin."""
from pathlib import Path
from score_io import LETTERS, load_score, part_measures, source_rows, visible

NOTE_HEADS = {0xf0cf, 0xf0fa, 0xf077, 0xf0bf}


def glyphs(page):
    for b in page.get_text("rawdict")["blocks"]:
        for line in b.get("lines", []):
            for span in line["spans"]:
                for c in span["chars"]:
                    if len(c["c"]) == 1:
                        yield *c["origin"], ord(c["c"]), span["size"]


def read_rows(page):
    g = sorted(glyphs(page), key=lambda a: a[0])
    clefs = sorted((a for a in g if a[2] == 0xf026), key=lambda a: a[1])
    paths = page.get_drawings()
    for x, y, _, font_size in clefs:
        unit = font_size / 8
        boundaries = sorted({round(path["rect"].x0, 2) for path in paths
            if path["rect"].width < 2.4 and abs(path["rect"].y0-(y-6*unit)) < .4
            and abs(path["rect"].y1-(y+2*unit)) < .4})
        bars = []
        for edge in boundaries:
            if bars and edge-bars[-1] < 4:
                bars[-1] = edge
            else:
                bars.append(edge)
        row = [a for a in g if a[0] > x+16 and y-34 < a[1] < y+16 and a[2] in NOTE_HEADS]
        yield y, unit, bars, row


def verify_staff(pdf, xml, part_id=""):
    import pymupdf
    expected = source_rows(part_measures(load_score(xml), part_id))
    matched = 0
    issues = []
    with pymupdf.open(pdf) as d:
        raw = [(page_i, row) for page_i,p in enumerate(d,1) for row in read_rows(p)]
        if not raw or not any(row[1][2] for row in raw):
            return {"status":"unsupported_profile","reason":"未发现可识别的五线谱矢量；扫描谱或其他字体需要人工或另一种识别配置"}
        if len(expected)!=len(raw):
            issues.append(f"分行数量不同：PDF {len(raw)}，MusicXML {len(expected)}")
        for ((page, ms),(actual_page,(y,unit,bars,shape))) in zip(expected,raw):
            shown=list(visible(ms))
            label=ms[0].get("number")
            if page!=actual_page or len(bars)!=len(shown):
                issues.append(f"第 {label} 小节所在行：分页或小节数不同")
                continue
            previous=0
            for (m,_),boundary in zip(shown,bars,strict=True):
                glyph=[(x,c,h,s) for x,c,h,s in shape if previous<x<boundary]
                previous=boundary
                notes=m.findall("note/pitch")
                num=m.get("number")
                if len(glyph)!=len(notes):
                    issues.append(f"第 {num} 小节：PDF 音头 {len(glyph)}，XML {len(notes)}")
                    continue
                for i,(n,(_,gy,_,_)) in enumerate(zip(notes,glyph,strict=True),1):
                    absolute=32+round((y-gy)/unit)
                    native=(LETTERS[absolute%7],str(absolute//7))
                    if native!=(n.findtext("step"),n.findtext("octave")):
                        issues.append(f"第 {num} 小节第 {i} 音：音级或八度与 PDF 谱位不同")
                    else:
                        matched+=1
    return {"status":"staff_positions_checked" if not issues else "review_needed",
            "matched_noteheads":matched,"issues_count":len(issues),"issues":issues[:100],
            "limits":"仅支持本项目校准的高音谱号 Finale 矢量字体；只查谱位、栏线、分行，不证明临时升降号、节奏或其他标记。"}
