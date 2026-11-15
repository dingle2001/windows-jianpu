"""Shared MusicXML loading, validation and source layout."""
from pathlib import Path
from zipfile import ZipFile
from defusedxml import ElementTree as XML
from fractions import Fraction
import re

TONIC_LABELS = ("bC", "bG", "bD", "bA", "bE", "bB", "F", "C", "G", "D", "A", "E", "B", "#F", "#C")
TONICS = {i: (s, s[-1], -1 if s.startswith("b") else 1 if s.startswith("#") else 0)
          for i, s in enumerate(TONIC_LABELS, -7)}
LETTERS = "CDEFGAB"
STEPS = (0, 2, 4, 5, 7, 9, 11)
MAX_XML = 16 * 1024 * 1024


def read_limited(path):
    with path.open("rb") as f:
        data = f.read(MAX_XML + 1)
    if len(data) > MAX_XML:
        raise ValueError(f"输入超过 16 MB：{path.name}")
    return data


def load_score(path):
    path = Path(path)
    if path.suffix.lower() == ".mxl":
        with ZipFile(path) as z:
            def entry(name):
                with z.open(name) as f:
                    data = f.read(MAX_XML + 1)
                if len(data) > MAX_XML:
                    raise ValueError("MXL 内的 XML 超过 16 MB")
                return data
            manifest = XML.fromstring(entry("META-INF/container.xml"))
            members = [n.get("full-path") for n in manifest.iter() if n.tag.rsplit("}", 1)[-1] == "rootfile"]
            if not members or not members[0]:
                raise ValueError("MXL 缺少谱面路径")
            doc = XML.fromstring(entry(members[0]))
    elif path.suffix.lower() in (".xml", ".musicxml"):
        doc = XML.fromstring(read_limited(path))
    else:
        raise ValueError("请使用 .xml、.musicxml 或 .mxl")
    for elem in doc.iter():
        elem.tag = elem.tag.rsplit("}", 1)[-1]
    if doc.tag != "score-partwise":
        raise ValueError("当前只支持 score-partwise MusicXML")
    return doc


def part_measures(doc, part_id=""):
    parts = doc.findall("part")
    if part_id:
        parts = [part for part in parts if part.get("id") == part_id]
    if len(parts) != 1:
        choices = [p.get("id") for p in doc.findall("part")]
        raise ValueError(f"需确定唯一声部，请填写 part_id。已知声部：{choices}")
    ms = parts[0].findall("measure")
    if not ms:
        raise ValueError("该声部无小节")
    for m in ms:
        label = m.get("number", "")
        if not re.fullmatch(r"[\w.-]{1,32}", label):
            raise ValueError(f"不支持的小节号：{label!r}")
        if m.find("backup") is not None or m.find("forward") is not None or m.find("note/chord") is not None:
            raise ValueError(f"第 {label} 小节包含和弦、多声部或隐含位移，需先整理成单旋律")
        if m.find("attributes/transpose") is not None:
            raise ValueError(f"第 {label} 小节含移调乐器信息，请先确定书面音和实音的口径")
        if any(b.find("repeat") is not None or b.find("ending") is not None for b in m.findall("barline")):
            raise ValueError(f"第 {label} 小节含反复或房子，当前版本需要手工处理")
        if not m.findall("note"):
            raise ValueError(f"第 {label} 小节没有音符或显式休止符")
    return ms


def source_rows(ms, measures_per_line=0):
    if not 0 <= measures_per_line <= 16:
        raise ValueError("measures_per_line 应为 0 到 16")
    pending = 0
    rows = []
    page = 1
    for m in ms:
        rule = m.find("print")
        new_page = rule is not None and rule.get("new-page") == "yes"
        new_row = new_page or (rule is not None and rule.get("new-system") == "yes")
        if not rows or new_row or (measures_per_line and len(rows[-1][1]) >= measures_per_line and not pending):
            if pending:
                raise ValueError(f"多小节休止跨越行界，第 {m.get('number')} 小节前需要修正 MusicXML")
            if rows and new_page:
                page += 1
            rows.append((page, []))
        rows[-1][1].append(m)
        pending = pending-1 if pending else int(m.findtext("attributes/measure-style/multiple-rest", "1"))-1
    if pending:
        raise ValueError("多小节休止范围超出声部")
    return rows


def visible(measures):
    skip = 0
    for m in measures:
        if skip:
            if m.find("note/rest[@measure='yes']") is None or m.find("direction") is not None or (skip>1 and m.find("barline") is not None):
                raise ValueError(f"多小节休止吞掉了第 {m.get('number')} 小节里的信息")
            skip -= 1
            continue
        count = int(m.findtext("attributes/measure-style/multiple-rest", "1"))
        if count < 1 or (count > 1 and m.find("note/rest[@measure='yes']") is None):
            raise ValueError(f"第 {m.get('number')} 小节的多小节休止不合法")
        yield m, count
        skip = count - 1
    if skip:
        raise ValueError("多小节休止超出本行")


def inspect_score(doc):
    part_names = {p.get("id"): p.findtext("part-name", "") for p in doc.findall("part-list/score-part")}
    return {
        "title": doc.findtext("work/work-title") or doc.findtext("movement-title") or "",
        "parts": [{"id": p.get("id"), "name": part_names.get(p.get("id"), ""),
                   "measures": len(p.findall("measure")),
                   "voices": sorted({n.findtext("voice", "1") for n in p.findall("measure/note")}),
                   "explicit_system_breaks": sum(x.get("new-system") == "yes" or x.get("new-page") == "yes" for x in p.findall("measure/print"))}
                  for p in doc.findall("part")]
    }
