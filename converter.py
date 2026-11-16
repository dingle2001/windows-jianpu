"""Build an editable JPword draft from one checked MusicXML melody."""
from pathlib import Path
from collections import Counter, defaultdict
from fractions import Fraction
import re

from jpword_layout import Label, PAGE_BREAK, ROW_END, apply_row_gap, multirest as native_rest, paginate_rows, place_labels, text_line
from score_io import TONICS, LETTERS, STEPS, load_score, part_measures, source_rows, visible

DURATION = {"whole": Fraction(4), "half": Fraction(2), "quarter": Fraction(1),
            "eighth": Fraction(1, 2), "16th": Fraction(1, 4), "32nd": Fraction(1, 8)}
TUPLET_RATIOS = {3: 2, 5: 4, 6: 4, 7: 4, 9: 8, 10: 8}


def often(m, n, x, y, body):
    return f"Often@{m},{n}({x:.2f},{y:.2f}) = {body}, {{}}, [], $FF000000, True"


def safe_text(value):
    return " ".join(value.split()).replace(",", "，").replace("{", "｛").replace("}", "｝")


def note_pitch(note, tonic):
    _, letter, base_alter = tonic
    base = LETTERS.index(letter)
    step = LETTERS.index(note.findtext("pitch/step"))
    octave = int(note.findtext("pitch/octave"))
    alter = Fraction(note.findtext("pitch/alter", "0"))
    octave_marks, degree = divmod(7 * (octave - 4) + step - base, 7)
    accidental = 12 * (octave - 4 - octave_marks) + STEPS[step] + alter - STEPS[base] - base_alter - STEPS[degree]
    if accidental.denominator != 1 or abs(accidental) > 2:
        raise ValueError("不支持的微分音/临时升降，请手工核对")
    mark = ("#" * int(accidental)) if accidental > 0 else "b" * int(-accidental)
    return mark, str(degree + 1) + ("g" * octave_marks if octave_marks >= 0 else "d" * -octave_marks)


def length_token(n, division):
    typ = n.findtext("type")
    if typ not in DURATION:
        raise ValueError(f"不支持的时值类型：{typ}")
    dots = n.findall("dot")
    q = DURATION[typ] * sum(Fraction(1, 2 ** i) for i in range(len(dots) + 1))
    tm = n.find("time-modification")
    if tm is not None:
        actual, normal = (int(tm.findtext(t)) for t in ("actual-notes", "normal-notes"))
        if TUPLET_RATIOS.get(actual) != normal:
            raise ValueError(f"非常规连音组 {actual}:{normal} 需人工确认")
        if tm.find("normal-type") is not None and tm.findtext("normal-type") != typ:
            raise ValueError("含异类 normal-type 的连音组需要人工处理")
        q *= Fraction(normal, actual)
    if q != Fraction(int(n.findtext("duration")), division):
        raise ValueError(f"记谱和时值不一致：{typ} 记作 {q} 拍")
    if typ in ("half", "whole"):
        if q.denominator != 1:
            raise ValueError("非常规长时值需人工确认")
        return ["0"] * int(q) if n.find("rest") is not None else ["-" * (int(q) - 1)]
    return ["_" * {"quarter": 0, "eighth": 1, "16th": 2, "32nd": 3}[typ] + "." * len(dots)]


def header(template, title, instrument, subtitle, composer, key):
    source = Path(template).read_text(encoding="utf-16")
    head, marker, _ = source.partition(".Voice")
    if not marker or ".Title" not in head:
        raise ValueError("模板需为 JPword 原生 UTF-16 .jpwabc 工程")
    for field, value in {"Intro": instrument, "Title": title, "SubTitle": subtitle,
                         "KeyAndMeters": key, "WordsByAndMusicBy": composer}.items():
        head, count = re.subn(rf"(?m)^{field} = [^\n]*$", lambda _: field + " = " + value, head)
        if count != 1:
            raise ValueError(f"模板缺少唯一的 {field} 字段")
    return head


def separate_chords(measure, label):
    notes = []
    members = {}
    for note in measure.findall("note"):
        if note.find("chord") is None:
            notes.append(note)
            members[note] = []
        elif (not notes or notes[-1].find("pitch") is None or note.find("pitch") is None
              or note.findtext("duration") != notes[-1].findtext("duration")
              or note.findtext("voice", "1") != notes[-1].findtext("voice", "1")
              or note.find("grace") is not None):
            raise ValueError(f"第 {label} 小节叠音的音高或时值不一致")
        elif any(note.find(tag) is not None for tag in ("tie", "notations")):
            raise ValueError(f"第 {label} 小节的从属叠音带独立演奏标记，请先核对")
        else:
            members[notes[-1]].append(note)
    return notes, members


def convert(xml, template, *, part_id="", measures_per_line=0, title="", instrument="", subtitle="", row_gap_mm=13.0, page_starts=None):
    doc = load_score(xml)
    ms = part_measures(doc, part_id, allow_native=True)
    if not 0 <= row_gap_mm <= 30:
        raise ValueError("谱行间距须为 0～30 mm")
    rows = paginate_rows(source_rows(ms, measures_per_line), page_starts)
    physical_index = {id(m): i for i,m in enumerate(ms)}
    if len(rows) == 1 and len(list(visible(ms))) > 12:
        raise ValueError("MusicXML 无分行标记。先按原谱录入 print，或显式设置每行小节数生成暂排稿")
    warnings = []
    if measures_per_line:
        warnings.append("启用了自动分行，请与原 PDF 逐行对齐后再定稿")
    if len({page for page, row in rows}) == 1:
        warnings.append("MusicXML 未提供多页分页信息，需在 JPword 确认实际分页")
    marks = Counter()
    title = title or doc.findtext("work/work-title") or doc.findtext("movement-title") or Path(xml).stem
    identity = part_id or doc.find("part").get("id")
    pname = next((n.findtext("part-name", "") for n in doc.findall("part-list/score-part") if n.get("id") == identity), "")
    composer = next((n.text or "" for n in doc.findall("identification/creator") if n.get("type") == "composer"), "")
    tonic = TONICS[0]
    beat_count, beat_type = 4, 4
    division = 0
    initial = None
    engraving = []
    attachments = []
    layout = []
    slurs = {}
    ties = set()
    open_wedge = {}
    midx = 0
    for row_number, (page, measures) in enumerate(rows, 1):
        rendered = []
        labels = []
        slots = {}
        for measure, multirest in visible(measures):
            midx += 1
            label = measure.get("number")
            local = f"第 {label} 小节"
            prefix = []
            for attr in measure.findall("attributes"):
                division = int(attr.findtext("divisions", str(division)))
                if attr.find("key") is not None:
                    fifths = attr.findtext("key/fifths")
                    if fifths is None or int(fifths) not in TONICS:
                        raise ValueError(local + "存在不支持的复合调号")
                    tonic = TONICS[int(fifths)]
                    if midx > 1:
                        labels.append(Label(midx, 1, "{1="+tonic[0]+"}", "key"))
                time = attr.find("time")
                if time is not None:
                    if len(time.findall("beats")) != 1 or len(time.findall("beat-type")) != 1:
                        raise ValueError(local + "存在复合拍号，请手工处理")
                    beat_count = int(time.findtext("beats"))
                    beat_type = int(time.findtext("beat-type"))
                    prefix.append(f"{beat_count}/{beat_type}")
            if initial is None:
                initial = f"{{1={tonic[0]},{beat_count}/{beat_type}}}"
            if division <= 0 or beat_count <= 0 or beat_type not in (2, 4, 8, 16):
                raise ValueError(local + "缺少 divisions 或拍号不受支持")
            if measure is measures[0] and midx > 1:
                labels.append(Label(midx, 1, "{bny:"+label+",1,0.00}", "bar_number"))
            note_list, chord_members = separate_chords(measure, label)
            target_beats = Fraction(4 * beat_count, beat_type)
            total = sum(Fraction(int(n.findtext("duration", "0")), division) for n in note_list)
            if total != target_beats:
                raise ValueError(local + f"时值合计 {total} 拍，拍号要求 {target_beats} 拍；请先核对弱起或识别结果")
            if len({n.findtext("voice", "1") for n in note_list}) != 1:
                raise ValueError(local + "包含多个 voice")
            written = []
            anchor_map = []
            grace = []
            grace_slurs = set()
            altered = set()
            arrow_end = {}
            for event in note_list:
                if (event.findtext("notations/other-notation") or "").strip() == "source slur ends in an arrowhead":
                    for arc in event.findall("notations/slur"):
                        if arc.get("type") == "stop":
                            arrow_end[arc.get("number", "1")] = event
            for n in note_list:
                if n.find("pitch") is not None:
                    accidental, name = note_pitch(n, tonic)
                    if accidental:
                        altered.add(name)
                    elif name in altered:
                        accidental = "#b"
                        altered.remove(name)
                    pitch = accidental + name
                else:
                    pitch = "0"
                simultaneous = chord_members[n]
                if simultaneous:
                    chord = [pitch]
                    for member in simultaneous:
                        acc, degree = note_pitch(member, tonic)
                        if acc:
                            altered.add(degree)
                        elif degree in altered:
                            acc="#b"
                            altered.remove(degree)
                        chord.append(acc+degree)
                    pitch="["+ "".join(chord)+"]"
                    marks["chord_events"] += 1
                if n.find("grace") is not None:
                    if pitch == "0":
                        raise ValueError(local + "休止倚音需人工处理")
                    grace.append(pitch)
                    grace_slurs.update(a.get("number", "1") for a in n.findall("notations/slur") if a.get("type") == "start")
                    marks["grace"] += 1
                    continue
                anchor = len(written) + 1
                anchor_map.append(anchor)
                decoration = []
                for path, mark in [("articulations/accent", "ZhongYin"),
                                   ("articulations/staccato", "DunYin"), ("fermata", "YanYin"),
                                   ("articulations/tenuto", "BaoChiYin")]:
                    if n.find(f"notations/{path}") is not None:
                        decoration.append(mark)
                        marks[mark] += 1
                if n.find("notations/articulations/breath-mark") is not None:
                    attachments.append(often(midx, anchor, 1.15, -1.25, "HuanQi"))
                    marks["HuanQi"] += 1
                if n.find("notations/ornaments/trill-mark") is not None:
                    attachments.append(often(midx, anchor, 0, -2.25, "ChanYin"))
                    marks["ChanYin"] += 1
                for other in n.findall("notations/*"):
                    if other.tag not in {"articulations","ornaments","fermata","slur","tied","tuplet","other-notation"}:
                        warnings.append(f"{local} 的 {other.tag} 需手工录入")
                    if other.tag in {"articulations","ornaments"}:
                        known = {"accent","staccato","breath-mark","tenuto"} if other.tag=="articulations" else {"trill-mark"}
                        warnings.extend(f"{local} 的 {symbol.tag} 需手工录入" for symbol in other if symbol.tag not in known)
                    if other.tag=="other-notation" and (other.text or "").strip()!="source slur ends in an arrowhead":
                        warnings.append(f"{local} 的自定义演奏符号需手工录入")
                opening, closing = [], []
                for arc in n.findall("notations/slur"):
                    key = arc.get("number", "1")
                    if arc.get("type") == "start":
                        slurs[key] = label
                        if key in arrow_end:
                            opening.append("{(0:0,0.00,1}")
                        else:
                            opening.append("(")
                    elif arc.get("type") == "stop":
                        if key in grace_slurs and key not in slurs:
                            grace_slurs.remove(key)
                            continue
                        if key not in slurs:
                            raise ValueError(local + "存在没有起点的连线")
                        slurs.pop(key)
                        closing.append(")")
                for tt in n.findall("notations/tuplet"):
                    if tt.get("type") == "start":
                        opening.append("{(" + n.findtext("time-modification/actual-notes") + "}")
                        marks["tuplet"] += 1
                    elif tt.get("type") == "stop":
                        closing.insert(0, ")")
                tie_continues = (n.find("tie[@type='start']") is not None
                                 and n.find("tie[@type='stop']") is not None)
                for tie in [] if tie_continues else n.findall("tie"):
                    tie_pitch = tuple(n.findtext("pitch/"+field,"0") for field in ("step","alter","octave"))
                    if tie.get("type") == "start":
                        ties.add(tie_pitch)
                        opening.append("(")
                    elif tie.get("type") == "stop":
                        if tie_pitch not in ties:
                            raise ValueError(local + "延音线缺少同音起点")
                        ties.remove(tie_pitch)
                        closing.insert(0, ")")
                deco = "{" + ",".join(decoration) + "}" if decoration else ""
                if n.find("rest[@measure='yes']") is not None:
                    rest = "0" + "_" * {2: 0, 4: 0, 8: 1, 16: 2}[beat_type]
                    fill = [rest] * (beat_count * (2 if beat_type == 2 else 1))
                    if multirest > 1:
                        rest = native_rest(target_beats)
                        fill = list(rest.tokens)
                        attachments.append(rest.attachment(midx, multirest))
                        marks["multirest"] += 1
                    fill[0] = "".join(opening) + deco + fill[0]
                    fill[-1] += "".join(closing)
                    written.extend(fill)
                else:
                    suffixes = length_token(n, division)
                    if len(suffixes) > 1 or suffixes == ["0"]:
                        body = suffixes
                    else:
                        body = [pitch + suffixes[0]]
                    body[0] = "".join(opening) + deco + ("{"+"".join(grace)+"}" if grace else "") + body[0]
                    body[-1] += "".join(closing)
                    written.extend(body)
                grace.clear()
                grace_slurs.clear()
            if grace:
                raise ValueError(local + "尾部倚音尚未与主音对齐")
            words_by_anchor = defaultdict(list)
            starts=[]
            cursor=0
            for n,a_idx in zip((n for n in note_list if n.find("grace") is None),anchor_map,strict=True):
                starts.append((cursor,a_idx))
                cursor+=int(n.findtext("duration","0"))
            source_cursor = 0
            for e in measure:
                if e.tag == "note" and e.find("chord") is None and e.find("grace") is None:
                    source_cursor += int(e.findtext("duration", "0"))
                if e.tag != "direction":
                    continue
                offset = source_cursor + int(e.findtext("offset", "0"))
                a = min(starts, key=lambda onset: abs(onset[0]-offset))[1]
                for dt in e.findall("direction-type/*"):
                    if dt.tag in {"words", "rehearsal"}:
                        word = safe_text(dt.text or "")
                        if dt.tag == "rehearsal" or dt.get("enclosure") == "rectangle":
                            labels.append(Label(midx, a, "{bny:"+word+",1,0.00}", "rehearsal"))
                        elif word:
                            words_by_anchor[a].append(word)
                    elif dt.tag == "metronome":
                        bpm = safe_text(dt.findtext("per-minute", ""))
                        if dt.findtext("beat-unit") == "quarter" and not dt.findall("beat-unit-dot") and bpm:
                            found = re.fullmatch(r"(\d+)(.*)",bpm)
                            if found:
                                words_by_anchor[a].append("{J="+found[1]+"}"+found[2])
                            else:
                                warnings.append(f"{local} 的速度标记 {bpm} 需手工录入")
                        else:
                            unit={"half":"二分音符","eighth":"八分音符","quarter":"四分音符"}.get(dt.findtext("beat-unit"),"拍")
                            if dt.find("beat-unit-dot") is not None:
                                unit="附点"+unit
                            if bpm:
                                words_by_anchor[a].append(unit+"＝"+bpm)
                                marks["tempo_text"]+=1
                            else:
                                warnings.append(f"{local} 的拍速单位需手工录入")
                    elif dt.tag == "dynamics":
                        for value in dt:
                            if value.tag in {"ppp","pp","p","mp","mf","f","ff","fff","sf","sfz","fp","sfp"}:
                                attachments.append(often(midx, a, 0, 1.65, "Force-"+value.tag))
                                marks["dynamic"] += 1
                            else:
                                attachments.append(text_line(midx,a,0,1.65,value.tag))
                                marks["dynamic_text"]+=1
                    elif dt.tag == "wedge":
                        ident=dt.get("number","1")
                        kind=dt.get("type")
                        if kind in ("crescendo","diminuendo"):
                            open_wedge[ident]=(midx,a,kind,label,row_number)
                        elif kind=="stop" and ident in open_wedge:
                            start,pos,opening_kind,start_label,start_row=open_wedge.pop(ident)
                            if start_row != row_number:
                                warnings.append(f"第 {start_label} 至 {label} 小节跨行渐强/渐弱需在 JPword 手工分段")
                            else:
                                size=min(155,max(7,8*(midx-start)+2.1*(a-pos)))
                                attachments.append(f"Dynamic@{start},{pos}(0.00,2.30) = {size:.2f}, {opening_kind == 'diminuendo'}, False, False, $FF000000, True")
                                marks["wedge"]+=1
                                warnings.append(f"第 {start_label} 小节起的渐强/渐弱宽度暂估，请按原谱复验")
                        else:
                            warnings.append(f"{local} 的 wedge 端点未配对，需人工确认")
                    else:
                        warnings.append(f"{local} 的 {dt.tag} 方向符号需手工录入")
            slots[midx] = len(written)
            labels.extend(Label(midx, a, "  ".join(words)) for a, words in words_by_anchor.items())
            last_measure = ms[physical_index[id(measure)]+multirest-1]
            bar_style = last_measure.findtext("barline/bar-style") or measure.findtext("barline/bar-style")
            if bar_style not in (None,"regular","light-light","light-heavy","heavy-light"):
                warnings.append(f"{local} 的小节线类型 {bar_style} 需手工确认")
            barline={"light-light":"||","light-heavy":"|]"}.get(bar_style,"|")
            next_index=physical_index[id(measure)]+multirest
            if last_measure.find("barline/repeat[@direction='backward']") is not None:
                barline=":|"
                marks["repeat_backward"]+=1
            elif next_index<len(ms) and ms[next_index].find("barline/repeat[@direction='forward']") is not None:
                barline="|:"
                marks["repeat_forward"]+=1
            rendered.append(" ".join(prefix+written+[barline]))
        positioned, lanes = place_labels(labels, slots)
        attachments.extend(positioned)
        new_page = row_number < len(rows) and rows[row_number][0] != page
        end = PAGE_BREAK if new_page else ROW_END
        engraving.append("  ".join(rendered) + "  " + end)
        layout.append({"page":page,"first":measures[0].get("number"),"last":measures[-1].get("number"),
                       "visible_measures":len(rendered),"label_lanes":lanes})
    if slurs or ties:
        raise ValueError("仍有未闭合的连线，请校对 MusicXML")
    if open_wedge:
        warnings.append("有未闭合的渐强/渐弱，请回到原谱核对")
    prefix = header(template, safe_text(title), safe_text(instrument or pname), safe_text(subtitle), safe_text(composer), initial)
    required_gap = 7.+3.3*max(item["label_lanes"] for item in layout)
    effective_gap = max(row_gap_mm, required_gap)
    prefix = apply_row_gap(prefix, effective_gap)
    score = prefix + ".Voice\n" + "\n".join(engraving) + "\n\n.Words\n\n.Attachments\n" + "\n".join(attachments) + "\n\n.Page\n"
    report = {"title":title,"source_measures":len(ms),"visible_measures":midx,"systems":len(rows),
              "explicit_pages":rows[-1][0],"row_gap_mm":effective_gap,"marks":dict(marks),"layout":layout,
              "warnings":list(dict.fromkeys(warnings)),
              "status":"draft_pending_source_and_native_review"}
    return score, report


def write_draft(output, score):
    path = Path(output)
    if path.suffix.lower() != ".jpwabc":
        raise ValueError("输出文件必须是 .jpwabc")
    with path.open("x", encoding="utf-16", newline="\r\n") as f:
        f.write(score)
