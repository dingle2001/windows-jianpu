"""Measure native JPword PDF output and calibrate editable long-rest attachments."""
from collections import defaultdict
from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path

import pymupdf

from jpword_layout import MM_PER_PT, REST_MARK, paginate_rows, replace_rest_mark
from score_io import load_score, part_measures, source_rows, visible

REST_CENTER_TOLERANCE_MM = 1.8
REST_OFFSET_SCALE = 2.4
PAGE_VERTICAL_CLEARANCE_MM = 10.


@dataclass
class System:
    top: float
    edges: list[float]
    rests: list


def native_systems(shapes, bar_height_pt):
    """Read the filled rectangles used for barlines in an outlined JPword print."""
    grouped = defaultdict(list)
    for shape in shapes:
        rect = shape["rect"]
        if shape["type"] != "f" or abs(rect.height-bar_height_pt)>=.15:
            continue
        x = rect.x0
        if not 0<rect.width<5:
            # JPword outlines a repeat's two stems and dots in one wider fill.
            stems = [item[1] for item in shape["items"] if item[0]=="re"
                     and abs(item[1].height-bar_height_pt)<.15 and 0<item[1].width<3]
            curves = sum(item[0]=="c" for item in shape["items"])
            if not (5<=rect.width<12 and len(stems)==2 and curves>=8):
                continue
            x = sum(stem.x0 for stem in stems)/len(stems)
        y = next((key for key in grouped if abs(key-rect.y0)<.15),rect.y0)
        grouped[y].append(x)
    systems = []
    for y, points in sorted(grouped.items()):
        groups = []
        for x in sorted(points):
            if groups and x-groups[-1][-1] <= 4:
                groups[-1].append(x)
            else:
                groups.append([x])
        systems.append(System(y,[sum(g)/len(g) for g in groups],[]))
    for shape in shapes:
        r = shape["rect"]
        if shape["type"]!="f" or not 5.5<r.height<17 or not 12<r.width<150:
            continue
        segments = []
        for item in shape["items"]:
            if item[0] == "l":
                a,b = item[1:]
                if abs(a.y-b.y)<.08 and abs(a.x-b.x)>r.width*.80:
                    segments.append((a.y,abs(a.x-b.x)))
        # The count and the thick bar are in one fill operation; the two
        # parallel edges distinguish it from beams, underlines, and hairpins.
        if not any(.45<abs(v[0]-w[0])<4. and abs(v[1]-w[1])<1
                   for i,v in enumerate(segments) for w in segments[i+1:]):
            continue
        matches = [system for system in systems if abs(system.top-r.y0)<4.8]
        if len(matches) == 1:
            matches[0].rests.append(r)
    for system in systems:
        system.rests.sort(key=lambda r:r.x0+r.x1)
    return systems


def inspect_export(pdf, xml, *, part_id="", measures_per_line=0, page_starts=None,
                   bar_height_pt=17.856, left_margin_mm=20.):
    rows = paginate_rows(source_rows(part_measures(load_score(xml),part_id,allow_native=True),
                                    measures_per_line),page_starts)
    expected = defaultdict(list)
    ordinal = 0
    for page, measures in rows:
        chart=list(visible(measures))
        rests=[(i,ordinal+i+1,m.get("number"),count) for i,(m,count) in enumerate(chart) if count>1]
        expected[page].append((len(chart),rests))
        ordinal += len(chart)
    page_grids={}
    rest_checks=[]
    issues=[]
    gaps=[]
    page_clearance={}
    with pymupdf.open(pdf) as document:
        for number,page in enumerate(document,1):
            shapes = page.get_drawings()
            ink = [shape["rect"] for shape in shapes
                   if shape["rect"].width < page.rect.width*.98
                   and shape["rect"].height < page.rect.height*.98]
            if ink:
                top = round((min(r.y0 for r in ink)-page.rect.y0)*MM_PER_PT,2)
                bottom = round((page.rect.y1-max(r.y1 for r in ink))*MM_PER_PT,2)
                page_clearance[number]={"top":top,"bottom":bottom}
                if min(top,bottom)<PAGE_VERTICAL_CLEARANCE_MM:
                    issues.append({"page":number,"issue":"page_vertical_clearance","top_mm":top,"bottom_mm":bottom})
            native=native_systems(shapes,bar_height_pt)
            page_grids[number]=[len(r.edges) for r in native]
            chart=expected.get(number,[])
            gaps.extend((number,round((b.top-a.top)*MM_PER_PT,2)) for a,b in zip(native,native[1:]))
            if page_grids[number]!=[count for count,_ in chart]:
                issues.append({"page":number,"issue":"system_or_bar_grid_differs"})
                continue
            for order,(system,(_,rests)) in enumerate(zip(native,chart,strict=True),1):
                if len(rests)!=len(system.rests):
                    issues.append({"page":number,"system":order,"issue":"rest_shapes_unmatched",
                                   "expected":len(rests),"observed":len(system.rests)})
                    continue
                for (index,visible_ordinal,measure,count),bounds in zip(rests,system.rests,strict=True):
                    left=system.edges[index-1] if index else left_margin_mm/MM_PER_PT
                    right=system.edges[index]
                    center=(bounds.x0+bounds.x1)/2
                    cell_center=(left+right)/2
                    if right-left < 8:
                        issues.append({"page":number,"measure":measure,"issue":"rest_cell_bounds_unusable"})
                        continue
                    dx=(cell_center-center)*MM_PER_PT
                    cap=(right-left-6)*MM_PER_PT
                    ok=(bounds.x0>=left+1.5 and bounds.x1<=right-1.5
                        and abs(dx)<=REST_CENTER_TOLERANCE_MM)
                    rest_checks.append({"page":number,"system":order,"measure":measure,"count":count,
                        "ordinal":visible_ordinal,"center_delta_mm":round(dx,3),
                        "width_cap_mm":round(cap,3),"inside_and_centered":ok,
                        "bbox_pt":[round(v,2) for v in bounds]})
                    if not ok:
                        issues.append({"page":number,"system":order,"measure":measure,"issue":"rest_needs_fit"})
        for number in expected.keys()-page_grids.keys():
            issues.append({"page":number,"issue":"page_missing"})
    return {"status":"review_needed" if issues else "pdf_layout_checked","pdf_sha256":pdf_sha256(pdf),
            "expected":{p:[n for n,_ in rs] for p,rs in expected.items()},"observed":page_grids,
            "rests":rest_checks,"issues":issues,
            "rest_center_tolerance_mm":REST_CENTER_TOLERANCE_MM,
            "page_vertical_clearance_mm":page_clearance,
            "minimum_system_separation_mm":min((v for _,v in gaps),default=None),
            "text_collision_check":"visual_required_for_outlined_text"}


def fit_exported_rests(project, report, *, offset_scale=REST_OFFSET_SCALE):
    """Convert measured page displacement to the template's editable x units."""
    if not 0.1 <= offset_scale <= 10:
        raise ValueError("长休止附件横向比例必须在 0.1 到 10 之间")
    broken={i["issue"] for i in report["issues"]}-{"rest_needs_fit","page_vertical_clearance"}
    if broken:
        raise ValueError(f"导出 PDF 无法和工程对齐：{', '.join(sorted(broken))}。先检查分页、栏线高度和导出版本。")
    text=Path(project).read_text(encoding="utf-16")
    widths={int(m[1]):float(m[5]) for m in REST_MARK.finditer(text)}
    changes=[]
    for rest in report["rests"]:
        if rest["inside_and_centered"]:
            continue
        ordinal=rest["ordinal"]
        cap=rest["width_cap_mm"]
        if cap<3:
            raise ValueError(f"第 {rest['measure']} 小节可用宽度太小，先在 JPword 拉开该小节")
        width=min(widths[ordinal],cap)
        page_delta = rest["center_delta_mm"]
        anchor_delta = page_delta / offset_scale
        text=replace_rest_mark(text,ordinal,anchor_delta,width)
        changes.append({"measure":rest["measure"],"offset_delta_mm":page_delta,
                        "anchor_delta":round(anchor_delta,3),"width_mm":width})
    return text,changes


def export_preview(pdf, page, dpi):
    with pymupdf.open(pdf) as document:
        if not 1<=page<=len(document):
            raise ValueError(f"页码超出范围：此 PDF 共 {len(document)} 页")
        return document[page-1].get_pixmap(dpi=dpi,alpha=False).tobytes("png")


def pdf_sha256(pdf):
    with Path(pdf).open("rb") as stream:
        return file_digest(stream,"sha256").hexdigest()
