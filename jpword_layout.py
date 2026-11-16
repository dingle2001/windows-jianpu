"""JPword 7.10m editing layout and native multi-measure rest attachments."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import math
import re

PAGE_BREAK = "$(True,0.00,1.00,True)"
ROW_END = "$(True)"
VERT_SPACING = re.compile(r"(?m)^(VertSpacing\s*=\s*[^,\n]+,\s*[^,\n]+,\s*[^,\n]+,\s*)[0-9.]+([ \t]*)$")
REST_MARK = re.compile(
    r"(?m)^Text@(\d+),(\d+)\((-?[\d.]+),(-?[\d.]+)\) = AttachText1, "
    r"\{ims:0,([\d.]+),(\d+)\}[^\n]*"
)
ATTACH_OPTIONS = "{}, [], $FF000000, True, False"
MM_PER_PT = 25.4 / 72
TEXT_ANCHOR = re.compile(r"(?m)^(Text@(\d+),(\d+)\()(-?[\d.]+),(-?[\d.]+)(\) = [^\n]*)$")


def text_line(measure, note, x_mm, y_mm, body):
    return f"Text@{measure},{note}({x_mm:.2f},{y_mm:.2f}) = AttachText1, {body}, {ATTACH_OPTIONS}"


def apply_row_gap(header, row_gap_mm):
    if not math.isfinite(row_gap_mm) or not 0 <= row_gap_mm <= 30:
        raise ValueError("谱行间距须为 0～30 mm")
    header, count = VERT_SPACING.subn(lambda m: f"{m[1]}{row_gap_mm:.2f}{m[2]}", header)
    if count == 1:
        return header
    if count > 1:
        raise ValueError("JPword 工程含重复的 VertSpacing")
    # The first three defaults come from the stock 7.10m examples.
    spacing = f"VertSpacing = 1.00, 0.30, 0.20, {row_gap_mm:.2f}\n"
    if ".Options\n" in header:
        return header.replace(".Options\n", ".Options\n" + spacing, 1)
    prefix, voice, rest = header.partition(".Voice\n")
    return prefix.rstrip() + "\n\n.Options\n" + spacing + "\n" + voice + rest


def paginate_rows(rows, page_starts=None):
    if page_starts is None:
        return rows
    expected = [m[0].get("number") for _, m in rows]
    positions = [str(n) for n in page_starts]
    if len(positions) != len(set(positions)) or any(n not in expected[1:] for n in positions):
        raise ValueError("换页小节必须是不重复的现有行首小节，且首行自动从第一页起")
    page = 1
    result = []
    for _, measures in rows:
        if measures[0].get("number") in positions:
            page += 1
        result.append((page, measures))
    return result


def replace_page_breaks(project, rows):
    """Apply new page breaks while preserving all systems and attachments."""
    prefix, voice_marker, remainder = project.partition("\n.Voice\n")
    voice, words_marker, suffix = remainder.partition("\n.Words\n")
    if not voice_marker or not words_marker:
        raise ValueError("JPword 工程缺少 .Voice 或 .Words")
    lines = voice.split("\n")
    systems = [i for i,line in enumerate(lines) if line.strip()]
    if len(systems) != len(rows):
        raise ValueError("JPword 工程谱行数与 MusicXML 不一致")
    for index, line_number in enumerate(systems):
        body, control, tail = lines[line_number].rpartition("$(")
        if not control or (control+tail).strip() not in {PAGE_BREAK, ROW_END}:
            raise ValueError(f"第 {index+1} 行含自定义谱行设置，请在 JPword 检查后分页")
        next_page = index+1 < len(rows) and rows[index+1][0] != rows[index][0]
        end = PAGE_BREAK if next_page else ROW_END
        lines[line_number] = body + end + tail[len(tail.rstrip()):]
    return prefix+voice_marker+"\n".join(lines)+words_marker+suffix


@dataclass(frozen=True)
class Rest:
    tokens: tuple[str, ...]
    anchor: int
    offset_mm: float
    width_mm: float

    def attachment(self, measure, count):
        return text_line(measure, self.anchor, self.offset_mm, -.50,
                         f"{{ims:0,{self.width_mm:.2f},{count}}}")


def multirest(beats):
    """Use the manual's fill-and-hide method with a central native attachment."""
    beats = Fraction(beats)
    if not 0 < beats <= 16 or beats.denominator not in (1, 2, 4):
        raise ValueError("长休止暂只支持四分音符的整数倍、1/2 或 1/4 拍")
    whole, part = divmod(beats, 1)
    tokens = []
    if whole:
        tokens.append("0" + "-" * (whole - 1))
    if part:
        tokens.append({Fraction(1,2):"0_",Fraction(1,4):"0__",Fraction(3,4):"0_."}[part])
    # Native single-anchor examples use 7.6 mm and 1.08 mm at two beats
    # and 14.5 mm and 2.52 mm at four. Exported geometry is used for final fit.
    width = max(5.2, min(22.0, .7 + 3.45 * float(beats)))
    offset = max(.35, .72 * float(beats)-.36)
    return Rest(tuple(t+"{C:0,None}" for t in tokens), 1, offset, width)


@dataclass(frozen=True)
class Label:
    measure: int
    note: int
    body: str
    kind: str = "words"

    def width(self):
        if self.kind == "bar_number":
            return 12.
        if self.kind == "key":
            return 14.
        value = re.sub(r"\{J=\d+\}", "tempo 000", self.body)
        value = re.sub(r"\{bny:([^,]+),[^}]+\}", r"\1", value)
        return max(8., sum(1.9 if c.isascii() else 4.1 for c in value) + 5.)


def place_labels(labels, slot_counts, width_mm=172.):
    """Pack above-staff labels into lanes, retaining their original note anchors."""
    bounds = {}
    width_unit = (width_mm - 8.) / sum(max(3, count+1) for count in slot_counts.values())
    cursor = 4.
    for measure, count in slot_counts.items():
        cell_width = max(3, count+1) * width_unit
        bounds[measure] = (cursor,cell_width)
        cursor += cell_width
    lanes = []
    output = []
    for label in sorted(labels, key=lambda l:(l.measure,l.note,l.kind == "words",l.kind)):
        left, cell_width = bounds[label.measure]
        position = left + cell_width * label.note / (slot_counts[label.measure]+1)
        width = min(label.width(),width_mm-4)
        nominal = position + (5. if label.kind == "words" and label.measure == next(iter(bounds)) else 0.)
        start = min(width_mm-width, nominal)
        occupied = (start-3.,start+width+3.)
        for level, intervals in enumerate(lanes):
            if all(occupied[0]>=other[1] or occupied[1]<=other[0] for other in intervals):
                break
        else:
            level = len(lanes)
            lanes.append([])
        lanes[level].append(occupied)
        output.append(text_line(label.measure,label.note,start-position,-6.4-5.3*level,label.body))
    return output, len(lanes)


def replace_rest_mark(project, ordinal, delta_mm, new_width_mm):
    """Apply a measured horizontal correction to one editable JPword attachment."""
    if ordinal < 1 or not math.isfinite(delta_mm) or not math.isfinite(new_width_mm) or new_width_mm < 3:
        raise ValueError("长休止位置或宽度无效")
    edits = 0
    def amend(m):
        nonlocal edits
        if int(m[1]) != ordinal:
            return m[0]
        edits += 1
        return m[0].replace(f"({m[3]},{m[4]})", f"({float(m[3])+delta_mm:.2f},{m[4]})", 1).replace(
            f"{{ims:0,{m[5]},{m[6]}}}", f"{{ims:0,{new_width_mm:.2f},{m[6]}}}", 1)
    updated = REST_MARK.sub(amend, project)
    if edits != 1:
        raise ValueError(f"第 {ordinal} 个可见谱格缺少唯一长休止附件")
    return updated


def move_attached_text(project, ordinal, note, match_text, dx_mm, dy_mm):
    """Move one text attachment selected by its score anchor and contents."""
    if not match_text or not all(math.isfinite(v) and abs(v) <= 50 for v in (dx_mm, dy_mm)):
        raise ValueError("请提供附件中的文字及 ±50 mm 内的位移")
    matches = [m for m in TEXT_ANCHOR.finditer(project)
               if int(m[2]) == ordinal and int(m[3]) == note and match_text in m[6]]
    if len(matches) != 1:
        raise ValueError("附件匹配结果须唯一，请确认可见小节序号、音符序号及文字")
    m = matches[0]
    if "{ims:" in m[6]:
        raise ValueError("长休止符请使用 JPword 导出校准工具")
    x, y = float(m[4])+dx_mm, float(m[5])+dy_mm
    return project[:m.start()] + f"{m[1]}{x:.2f},{y:.2f}{m[6]}" + project[m.end():], (x,y)
