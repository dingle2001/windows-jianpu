"""JPword local file MCP. UI export stays on the desktop."""
import argparse
import asyncio
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

from score_io import load_score, inspect_score
from converter import convert, write_draft
from audit import audit_project, audit_pdf_layout
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
                              measures_per_line: Lines=0, title: str="", instrument: str="", subtitle: str="") -> dict:
    """从已校对 MusicXML 单旋律生成一个新的 JPword UTF-16 工程，并返回分行表和待办。所有路径相对乐谱根目录，输出不得已存在。"""
    def work():
        target=scoped(output,{".jpwabc"},create=True)
        score,report=convert(scoped(source,MUSIC),scoped(template,{".jpwabc"}),part_id=part_id,
                            measures_per_line=measures_per_line,title=title,instrument=instrument,subtitle=subtitle)
        write_draft(target,score)
        return {"output":str(target.relative_to(ROOT)),**report}
    return await asyncio.to_thread(work)


@mcp.tool(annotations=READ)
async def jpword_audit_project(source: str, project: str, part_id: str="", measures_per_line: Lines=0) -> dict:
    """检查工程的可见小节、音高、时值、跳音、原生颤音等锚点。通过也仍需用 JPword 看实际谱面。"""
    return await asyncio.to_thread(lambda: audit_project(scoped(source,MUSIC),scoped(project,{".jpwabc"}),part_id,measures_per_line))


@mcp.tool(annotations=READ)
async def jpword_audit_export(source: str, exported_pdf: str, part_id: str="",measures_per_line: Lines=0,
                              bar_height_pt: Annotated[float,Field(gt=1,lt=100)]=17.856) -> dict:
    """按 JPword 7.10m 矢量版式读取实际分页和栏线。字号变化时须先校准栏线高度，仍需目视检查排版。"""
    return await asyncio.to_thread(lambda: audit_pdf_layout(scoped(exported_pdf,{".pdf"}),scoped(source,MUSIC),part_id,measures_per_line,bar_height_pt))


@mcp.prompt()
def jpword_rehearsal_workflow() -> str:
    """复用五线谱转排练简谱的标准步骤。"""
    return ("先盘点 MusicXML 并明确声部，逐行对照原五线谱。能识别矢量时运行源谱谱位检查，"
            "按原谱校对升降号、时值、连线、跳音▼、原生 tr、倚音、力度和换乐器。"
            "借用指定 JPword 模板另存转谱稿，并审核工程数据。"
            "用 Computer Use 在用户的 JPword 打开最新版并导出 PDF。逐页检查分行、分页、标记和裁切。"
            "不可将旧版 PDF 或结构通过当成最新演奏版验收；保留工程和本次导出的 PDF。")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=ROOT)
    ROOT=parser.parse_args().root.resolve(strict=True)
    if not ROOT.is_dir():
        parser.error("--root 必须是乐谱目录")
    mcp.run(transport="stdio")
