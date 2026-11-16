"""Independent checks against MusicXML and the JPword-exported PDF."""
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
import re

from score_io import TONICS, LETTERS, STEPS, load_score, part_measures, source_rows, visible
from converter import TUPLET_RATIOS
from jpword_layout import PAGE_BREAK, REST_MARK, paginate_rows

PITCH_PATTERN = r"[#b]*[0-7][gd]*"
PITCH = re.compile(r"([#b]*)([0-7])([gd]*)")
EVENT = rf"(?:\[(?:{PITCH_PATTERN})+\]|{PITCH_PATTERN})"
NOTE = re.compile(rf"({EVENT})(_*)(\.*)(-*)")
TOKEN = re.compile(rf"\{{[^}}]*\}}|{EVENT}_*\.*-*|[()]")
FLOW = re.compile(r"\|:|:\||\|\]|\|\||\|")
MARKS = {"articulations/staccato":"DunYin", "articulations/accent":"ZhongYin",
         "articulations/tenuto":"BaoChiYin", "fermata":"YanYin"}


def expected_events(measure, divisions):
    events = []
    for n in measure.findall("note"):
        p = n.find("pitch")
        q = Fraction(int(n.findtext("duration", "0")), divisions)
        if p is not None:
            letter = LETTERS.index(p.findtext("step"))
            pitch = 12 * (int(p.findtext("octave")) + 1) + STEPS[letter] + Fraction(p.findtext("alter", "0"))
            if n.find("chord") is not None:
                pitches, duration = events[-1]
                if duration != q:
                    raise ValueError("叠音时值不一致")
                events[-1] = (tuple(sorted((*pitches, pitch))), q)
            else:
                events.append(((pitch,), q))
        elif n.find("rest") is not None:
            if n.find("rest").get("measure") == "yes":
                events.extend([(None,Fraction(1,4))]*int(q*4))
            elif n.findtext("type") in ("half","whole"):
                events.extend([(None,Fraction(1))]*int(q))
            else:
                events.append((None,q))
        else:
            raise ValueError(f"第 {measure.get('number')} 小节无法判定音符类型")
    return events


def tokens(cell):
    cell = re.sub(r"^\s*\d+/\d+\s+", "", cell)
    found = TOKEN.findall(cell)
    if "".join(found) != re.sub(r"\s", "", cell):
        raise ValueError(f"工程含未支持的旋律格式：{cell[:80]}")
    return found


def decode(cell, tonic):
    accidental = {}
    group = []
    result = []
    marks = defaultdict(list)
    event_index = 0
    decorations = []
    _, letter, offset = tonic
    origin = 60 + STEPS[LETTERS.index(letter)] + offset

    def midi(match):
        symbol, degree, octaves, *_ = match.groups()
        k = degree + octaves
        if symbol:
            accidental[k] = symbol.count("#") - symbol.count("b")
        return origin + accidental.get(k, 0) + STEPS[int(degree)-1] + 12 * (octaves.count("g") - octaves.count("d"))

    for t in tokens(cell):
        note = NOTE.fullmatch(t)
        if note is None:
            m = re.fullmatch(r"\{\((\d+)\}", t)
            if m:
                count = int(m[1])
                if group or count not in TUPLET_RATIOS:
                    raise ValueError("嵌套或未知连音组")
                group = [count, Fraction(TUPLET_RATIOS[count], count)]
            elif t.startswith("{") and t.endswith("}"):
                inner = t[1:-1]
                pitches = list(PITCH.finditer(inner))
                if pitches and "".join(x[0] for x in pitches)==inner and all(x[2]!="0" for x in pitches):
                    result.extend(((midi(p),),Fraction(0)) for p in pitches)
                decorations.extend(k for k in inner.split(",") if k in MARKS.values())
            continue
        encoded, lines, dots, holds = note.groups()
        q = Fraction(1 + len(holds), 2 ** len(lines)) * sum(Fraction(1, 2**i) for i in range(1+len(dots)))
        if group:
            q *= group[1]
            group[0] -= 1
            if group[0]==0:
                group = []
        values = tuple(sorted(midi(m) for m in PITCH.finditer(encoded))) if encoded != "0" else None
        result.append((values,q))
        event_index += 1
        for d in decorations:
            marks[d].append(event_index)
        decorations.clear()
    if group:
        raise ValueError("连音组未闭合")
    return result, marks


def project_rows(path):
    data=Path(path).read_text(encoding="utf-16")
    if ".Voice" not in data or ".Attach" not in data:
        raise ValueError("工程缺少 Voice 或 Attachments")
    tail=data.partition(".Voice")[2].partition(".Attachments")
    voice=tail[0].partition(".Words")[0]
    raw=[line for line in voice.splitlines() if "$(" in line]
    return raw, tail[2]


def audit_project(xml, project, part_id="", measures_per_line=0, page_starts=None):
    ms=part_measures(load_score(xml),part_id,allow_native=True)
    indices={id(m): i for i,m in enumerate(ms)}
    rows=paginate_rows(source_rows(ms, measures_per_line), page_starts)
    raw, attachments=project_rows(project)
    if len(raw)!=len(rows):
        raise ValueError(f"分行不一致：源 {len(rows)} 行，工程 {len(raw)} 行。此检查适用于本项目生成的一行一系统格式")
    division=0
    tonic=TONICS[0]
    marks=Counter()
    project_rests=defaultdict(list)
    for marker in REST_MARK.finditer(attachments):
        project_rests[int(marker[1])].append(marker)
    expected_rests=set()
    generated_cells=0
    mark_anchors=defaultdict(set)
    for match in re.finditer(r"(?m)^Often@(\d+),(\d+)\([^)]*\) = (ChanYin|HuanQi),",attachments):
        mark_anchors[match[3]].add((int(match[1]),int(match[2])))
    targets=defaultdict(set)
    for ri,((page,measures),line) in enumerate(zip(rows,raw,strict=True),1):
        break_here=ri<len(rows) and rows[ri][0]!=page
        if (PAGE_BREAK in line)!=break_here:
            raise ValueError(f"第 {ri} 行分页与 MusicXML 不一致")
        body=line.partition("$(")[0]
        cells=FLOW.split(body)
        barlines=FLOW.findall(body)
        if cells[-1].strip():
            raise ValueError(f"第 {ri} 行末尾缺少小节线")
        chart=list(visible(measures))
        if len(cells)-1!=len(chart):
            raise ValueError(f"第 {ri} 行的小节数与 MusicXML 不一致")
        for cell,barline,(m,count) in zip(cells[:-1],barlines,chart,strict=True):
            generated_cells+=1
            label=m.get("number")
            division=int(m.findtext("attributes/divisions",str(division)))
            fifths=m.findtext("attributes/key/fifths")
            if fifths is not None:
                tonic=TONICS[int(fifths)]
                if generated_cells>1 and not re.search(rf"(?m)^Text@{generated_cells},1\(.*\{{1={re.escape(tonic[0])}\}}",attachments):
                    raise ValueError(f"第 {label} 小节缺少调号")
            if count > 1:
                expected_rests.add(generated_cells)
                native_marks = project_rests[generated_cells]
                if len(native_marks)!=1 or int(native_marks[0][6])!=count:
                    raise ValueError(f"第 {label} 小节多小节休止计数不符")
                hidden = [item for item in tokens(cell) if NOTE.fullmatch(item)]
                if (not hidden or int(native_marks[0][2]) > len(hidden)
                        or int(native_marks[0][2]) < 1 or float(native_marks[0][5]) <= 0
                        or cell.count("{C:0,None}") != len(hidden)):
                    raise ValueError(f"第 {label} 小节隐藏时值或长休止的锚点不符")
                marks["multirest"] += 1
            offset=indices[id(m)]+count
            ending=ms[offset-1].find("barline/repeat[@direction='backward']") is not None
            opening=offset<len(ms) and ms[offset].find("barline/repeat[@direction='forward']") is not None
            expected_bar = ":|" if ending else "|:" if opening else None
            if (expected_bar is not None and barline!=expected_bar) or (
                    expected_bar is None and barline in ("|:",":|")):
                raise ValueError(f"第 {label} 小节相邻的反复线不符")
            if expected_bar:
                marks["repeat_barlines"] += 1
            actual, found=decode(cell,tonic)
            exp=expected_events(m,division)
            if m.find("note/rest[@measure='yes']") is not None:
                if any(p is not None for p,q in actual) or sum(q for p,q in actual)!=sum(q for p,q in exp):
                    raise ValueError(f"第 {label} 小节整小节休止不符")
            elif actual!=exp:
                position=next((i for i,(a,b) in enumerate(zip(actual,exp),1) if a!=b), min(len(actual),len(exp))+1)
                raise ValueError(f"第 {label} 小节第 {position} 个事件有音高、时值或顺序差异")
            index=0
            wanted=defaultdict(list)
            for n in m.findall("note"):
                if n.find("chord") is not None:
                    continue
                if n.find("grace") is not None:
                    marks["grace"]+=1
                    continue
                index+=1
                for tag,mark in MARKS.items():
                    if n.find("notations/"+tag) is not None:
                        wanted[mark].append(index)
                        marks[mark]+=1
                for tag,mark in [("ornaments/trill-mark","ChanYin"),("articulations/breath-mark","HuanQi")]:
                    if n.find("notations/"+tag) is not None:
                        targets[mark].add((generated_cells,index))
                        marks[mark]+=1
                if n.find("rest") is not None and n.findtext("type") in ("half","whole"):
                    index+=int(Fraction(int(n.findtext("duration")),division))-1
            if dict(found)!=dict(wanted):
                raise ValueError(f"第 {label} 小节的跳音、重音或延长记号锚点不符")
            marks["pitched_events"]+=sum(len(p) for p,q in actual if p is not None)
    if set(project_rests)!=expected_rests:
        raise ValueError("工程存在多余长休止附件")
    if {k:v for k,v in mark_anchors.items() if v}!={k:v for k,v in targets.items() if v}:
        raise ValueError("原生 tr 或换气符号锚点不符")
    return {"status":"project_data_checked","systems":len(rows),"visible_measures":generated_cells,
            "explicit_pages":rows[-1][0],"marks":dict(marks)}


def audit_pdf_layout(pdf, xml, part_id="", measures_per_line=0, bar_height_pt=17.856):
    """Compatibility entry point for the native export geometry audit."""
    from jpword_pdf import inspect_export

    return inspect_export(pdf, xml, part_id=part_id, measures_per_line=measures_per_line,
                          bar_height_pt=bar_height_pt)
