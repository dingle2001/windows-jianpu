"""JPword local file MCP. UI export stays on the desktop."""
import argparse
import asyncio
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

from score_io import load_score, inspect_score, part_measures, source_rows
from converter import convert, write_draft
from audit import audit_project
from jpword_layout import apply_row_gap, move_attached_text, paginate_rows, replace_page_breaks
from jpword_pdf import REST_OFFSET_SCALE, export_preview, fit_exported_rests, inspect_export
from staff_pdf import verify_staff

mcp = FastMCP("jpword_mcp")
ROOT = Path(__file__).resolve().parent.parent
MUSIC = {".musicxml",".xml",".mxl"}


def scoped(relative, suffixes, create=False):
    rel = Path(relative)
    if rel.is_absolute() or rel.drive:
        raise ValueError("请提供相对于乐谱根目录的路径，例如 秦兵马俑/复校.xml")
    path = (ROOT/rel).resolve(strict=not create)
    if not path.is_relative_to(ROOT):
        raise ValueError("路径超出允许的乐谱根目录")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"只接受文件类型：{', '.join(sorted(suffixes))}")
    if create:
        if not path.parent.is_dir():
            raise ValueError("请先建立任务目录")
        if path.exists():
            raise ValueError("输出已存在，请换文件名，避免覆盖工程")
    elif not path.is_file():
        raise ValueError("输入必须是普通文件")
    return path


READ=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)
WRITE=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=False,openWorldHint=False)
Lines = Annotated[int,Field(ge=0,le=16,description="0 保留 MusicXML 的原分行；正数仅用于暂排")]
Gap = Annotated[float, Field(ge=0, le=30, description="JPword 垂直定位第四项，单位 mm")]
BarHeight = Annotated[float, Field(gt=1, lt=100)]
Margin = Annotated[float, Field(ge=0, lt=100)]
Offset = Annotated[float, Field(ge=-50, le=50)]
Ordinal = Annotated[int, Field(ge=1)]


@mcp.tool(annotations=READ)
async def jpword_inspect_musicxml(source: str) -> dict:
    """读取 MusicXML/MXL 的曲名、声部 ID、小节数和已有换行数量。路径相对乐谱根目录。"""
    return await asyncio.to_thread(lambda: inspect_score(load_score(scoped(source,MUSIC))))


@mcp.tool(annotations=READ)
async def jpword_verify_staff_pdf(original_pdf: str, source: str, part_id: str="") -> dict:
    """比对已知 Finale 矢量五线谱的栏线与音头谱位。扫描件和其他字体返回待人工校对。"""
    return await asyncio.to_thread(lambda: verify_staff(scoped(original_pdf,{".pdf"}),scoped(source,MUSIC),part_id))


@mcp.tool(annotations=WRITE)
async def jpword_create_draft(source: str, template: str, output: str, part_id: str="",
                              measures_per_line: Lines=0, title: str="", instrument: str="", subtitle: str="",
                              row_gap_mm: Gap=13., page_starts: list[str | int] | None=None) -> dict:
    """从已校对 MusicXML 单旋律生成一个新的 JPword UTF-16 工程，并返回分行表和待办。所有路径相对乐谱根目录，输出不得已存在。"""
    def work():
        target=scoped(output,{".jpwabc"},create=True)
        score,report=convert(scoped(source,MUSIC),scoped(template,{".jpwabc"}),part_id=part_id,
                            measures_per_line=measures_per_line,title=title,instrument=instrument,subtitle=subtitle,
                            row_gap_mm=row_gap_mm,page_starts=page_starts)
        write_draft(target,score)
        return {"output":str(target.relative_to(ROOT)),**report}
    return await asyncio.to_thread(work)


@mcp.tool(annotations=READ)
async def jpword_audit_project(source: str, project: str, part_id: str="", measures_per_line: Lines=0,
                              page_starts: list[str | int] | None=None) -> dict:
    """检查工程的可见小节、音高、时值、跳音、原生颤音等锚点。通过也仍需用 JPword 看实际谱面。"""
    return await asyncio.to_thread(lambda: audit_project(scoped(source,MUSIC),scoped(project,{".jpwabc"}),
                                                         part_id,measures_per_line,page_starts))


@mcp.tool(annotations=WRITE)
async def jpword_set_row_gap(project: str, output: str, row_gap_mm: Gap) -> dict:
    """调整现有工程的全局谱行间距并另存，保留小节及手动修改。另存后在 JPword 检查分页和裁切。"""
    def work():
        target = scoped(output, {".jpwabc"}, create=True)
        original = scoped(project, {".jpwabc"}).read_text(encoding="utf-16")
        write_draft(target, apply_row_gap(original, row_gap_mm))
        return {"output": str(target.relative_to(ROOT)), "row_gap_mm": row_gap_mm}
    return await asyncio.to_thread(work)


@mcp.tool(annotations=WRITE)
async def jpword_repaginate(source: str, project: str, output: str, page_starts: list[str | int],
                           current_page_starts: list[str | int] | None=None, part_id: str="",
                           measures_per_line: Lines=0) -> dict:
    """按指定行首小节重新分页并另存，保留调号、谱行、音符和手工修改。"""
    def work():
        xml = scoped(source, MUSIC)
        existing = scoped(project, {".jpwabc"})
        target = scoped(output, {".jpwabc"}, create=True)
        audit_project(xml, existing, part_id, measures_per_line, current_page_starts)
        measures = part_measures(load_score(xml), part_id, allow_native=True)
        rows = paginate_rows(source_rows(measures, measures_per_line), page_starts)
        updated = replace_page_breaks(existing.read_text(encoding="utf-16"), rows)
        write_draft(target, updated)
        return {"output": str(target.relative_to(ROOT)), "page_starts": page_starts,
                "explicit_pages": rows[-1][0], "reexport_required": True}
    return await asyncio.to_thread(work)


@mcp.tool(annotations=WRITE)
async def jpword_move_attached_text(project: str, output: str, visible_measure: Ordinal, note: Ordinal,
                                   match_text: str, dx_mm: Offset=0., dy_mm: Offset=0.) -> dict:
    """根据导出页的视觉结果移动唯一文字附件并另存；x 向右为正，y 向下为正。"""
    def work():
        target = scoped(output, {".jpwabc"}, create=True)
        original = scoped(project, {".jpwabc"}).read_text(encoding="utf-16")
        updated, (x,y) = move_attached_text(original,visible_measure,note,match_text,dx_mm,dy_mm)
        write_draft(target, updated)
        return {"output": str(target.relative_to(ROOT)), "anchor": [visible_measure,note],
                "x_mm": x, "y_mm": y, "reexport_required": True}
    return await asyncio.to_thread(work)


@mcp.tool(annotations=READ)
async def jpword_audit_export(source: str, exported_pdf: str, part_id: str="",measures_per_line: Lines=0,
                              bar_height_pt: BarHeight=17.856, left_margin_mm: Margin=20.,
                              page_starts: list[str | int] | None=None) -> dict:
    """检查 JPword 7.10m 矢量导出的分页、栏线、长休止符居中和谱行实际距离。"""
    return await asyncio.to_thread(lambda: inspect_export(scoped(exported_pdf,{".pdf"}),scoped(source,MUSIC),
        part_id=part_id,measures_per_line=measures_per_line,page_starts=page_starts,
        bar_height_pt=bar_height_pt,left_margin_mm=left_margin_mm))


@mcp.tool(annotations=WRITE)
async def jpword_fit_multirests(source: str, project: str, exported_pdf: str, output: str,
                              part_id: str="", measures_per_line: Lines=0, bar_height_pt: BarHeight=17.856,
                              left_margin_mm: Margin=20., page_starts: list[str | int] | None=None,
                              offset_scale: Annotated[float, Field(ge=.1, le=10)]=REST_OFFSET_SCALE) -> dict:
    """依据该工程刚导出的矢量 PDF 微调长休止符，然后另存。需在 JPword 重新导出复查。"""
    def work():
        src = scoped(source, MUSIC)
        score = scoped(project, {".jpwabc"})
        target = scoped(output, {".jpwabc"}, create=True)
        audit_project(src, score, part_id, measures_per_line, page_starts)
        report = inspect_export(scoped(exported_pdf,{".pdf"}),src,part_id=part_id,
            measures_per_line=measures_per_line,page_starts=page_starts,
            bar_height_pt=bar_height_pt,left_margin_mm=left_margin_mm)
        updated, changes = fit_exported_rests(score, report, offset_scale=offset_scale)
        write_draft(target, updated)
        return {"output": str(target.relative_to(ROOT)), "changes": changes,
                "offset_scale": offset_scale, "source_pdf_sha256": report["pdf_sha256"], "reexport_required": True}
    return await asyncio.to_thread(work)


@mcp.tool(annotations=READ)
async def jpword_preview_export_page(exported_pdf: str, page: Annotated[int, Field(ge=1)]=1,
                                    dpi: Annotated[int, Field(ge=72, le=180)]=120) -> Image:
    """以图像显示 JPword 实际导出的指定页，用于人工检查文字碰撞、裁切及标记。"""
    data = await asyncio.to_thread(lambda: export_preview(scoped(exported_pdf,{".pdf"}),page,dpi))
    return Image(data=data,format="png")


@mcp.prompt()
def jpword_rehearsal_workflow() -> str:
    """复用五线谱转排练简谱的标准步骤。"""
    return ("先盘点 MusicXML 并明确声部，逐行对照原五线谱。能识别矢量时运行源谱谱位检查，"
            "按原谱校对升降号、时值、连线、跳音▼、原生 tr、倚音、力度和换乐器。"
            "借用指定 JPword 模板另存转谱稿，并审核工程数据。"
            "用 Computer Use 在 JPword 确认已打开最新版，以虚拟鼠标点击「导出打印」并选择矢量 PDF。"
            "每出现一次本次导出的确认，读清新画面后点击「是」，包括第二次确认。检查 PDF 已生成。"
            "检查谱行间距和长休止符。"
            "按实测修正偏移后重新导出，通过逐页图像检查插入文字、演奏标记和裁切。"
            "保留对应版本的工程和 PDF。")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=ROOT)
    ROOT=parser.parse_args().root.resolve(strict=True)
    if not ROOT.is_dir():
        parser.error("--root 必须是乐谱目录")
    mcp.run(transport="stdio")
