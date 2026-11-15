"""CLI using the same conversion and validation functions as the MCP server."""
import argparse
import json
from pathlib import Path
import sys

from audit import audit_pdf_layout, audit_project
from converter import convert, write_draft
from score_io import inspect_score, load_score
from staff_pdf import verify_staff


def main():
    cli=argparse.ArgumentParser(description="JPword 单旋律转谱与复核")
    commands=cli.add_subparsers(dest="command",required=True)
    for name in ("inspect","verify-source","convert","audit","check-pdf"):
        cmd=commands.add_parser(name)
        cmd.add_argument("source",type=Path,help="MusicXML/MXL")
        if name!="inspect":
            cmd.add_argument("--part-id",default="")
        if name in {"verify-source","check-pdf"}:
            cmd.add_argument("pdf",type=Path)
        if name in {"convert","audit","check-pdf"}:
            cmd.add_argument("--measures-per-line",type=int,default=0,help="0 保留原分行；正数为暂排")
        if name in {"convert","audit"}:
            cmd.add_argument("project",type=Path)
        if name=="convert":
            cmd.add_argument("--template",type=Path,required=True)
            cmd.add_argument("--title",default="")
            cmd.add_argument("--instrument",default="")
            cmd.add_argument("--subtitle",default="")
        if name=="check-pdf":
            cmd.add_argument("--bar-height-pt",type=float,default=17.856)
    a=cli.parse_args()
    try:
        if a.command=="inspect":
            result=inspect_score(load_score(a.source))
        elif a.command=="verify-source":
            result=verify_staff(a.pdf,a.source,a.part_id)
        elif a.command=="convert":
            score,result=convert(a.source,a.template,part_id=a.part_id,measures_per_line=a.measures_per_line,
                                 title=a.title,instrument=a.instrument,subtitle=a.subtitle)
            write_draft(a.project,score)
            result["output"]=str(a.project.resolve())
        elif a.command=="audit":
            result=audit_project(a.source,a.project,a.part_id,a.measures_per_line)
        else:
            result=audit_pdf_layout(a.pdf,a.source,a.part_id,a.measures_per_line,a.bar_height_pt)
    except (RuntimeError,ValueError,OSError) as e:
        cli.exit(1,f"处理失败：{e}\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result.get("status") in {"review_needed","unsupported_profile"} else 0


if __name__=="__main__":
    sys.exit(main())
