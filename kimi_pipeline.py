"""Kimi Code 贯通入口：从原始五线谱 PDF 一路推进到 JPword 原生导出审计与定稿。

复用 workflow.py 的 prepare/handoff/render/finalize 与本地文件 MCP 的审计能力。
每个阶段完成后写入任务目录的 .kimi-pipeline.json；人工核对、JPword 桌面导出或
窗口不可用时直接退出，修复后重跑同一命令即从最近一步继续。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import workflow as wf
from jpword_pdf import inspect_export

HERE = Path(__file__).resolve().parent
STAGES = ["prepare", "review", "handoff", "render", "jpword-export", "audit", "finalize"]
WAIT_REVIEW = 2   # 等待人工保存 reviewed.musicxml / review-notes.md
WAIT_EXPORT = 3   # 等待 JPword 桌面导出落盘

EXPORT_INSTRUCTIONS = """JPword 桌面导出（本机已验证的操作约定）：
  1. 保持 JPword 单实例运行，窗口标题以「JP-Word->」开头；
  2. 用 Kimi CU 虚拟鼠标操作，Codex CU 与 Kimi CU 串行占用输入，不要并行驱动桌面；
  3. 打开工程：{project}
  4. 文件 → 导出 → PDF文件…（快捷键 Shift+Ctrl+F2），逐帧读取画面；
  5. 两次确认（导出提示、健康体检警告）均点击「是」；
  6. 另存为同名矢量 PDF 到任务目录；
  7. 出现「是否要在资源管理器中打开」时点击「否」；
  8. 将导出的 PDF 复制为：{expected}
完成后重新运行本命令继续。"""

SHA_PREFIX = "PDF SHA-256:"


def review_path(job, edition):
    return job / edition / "print-review.md"


def review_sha(text):
    for line in text.splitlines():
        if line.startswith(SHA_PREFIX):
            return line[len(SHA_PREFIX):].strip()
    return None


def review_body(text):
    """目检正文：去掉哈希绑定行与空白行后的内容。"""
    return "\n".join(line for line in text.splitlines()
                     if not line.startswith(SHA_PREFIX)).strip()


def state_path(job):
    return job / ".kimi-pipeline.json"


def load_state(job):
    path = state_path(job)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"done": [], "params": {}}


def save_state(job, state):
    state_path(job).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")


def base_ns(a, **kw):
    return argparse.Namespace(config=a.config, scratch=a.scratch, **kw)


def do_prepare(a, rt, job):
    if job.is_dir():
        entries = [p for p in job.iterdir() if p.name != state_path(job).name]
        if not entries:
            shutil.rmtree(job)  # workflow.prepare 要求任务目录不存在
    wf.prepare(base_ns(a, pdf=a.pdf, job=job, draft=a.draft, vector_audit=a.vector_audit), rt)


def do_review(a, rt, job):
    xml = job / "reviewed.musicxml"
    notes = job / "review-notes.md"
    missing = [p.name for p in (xml, notes) if not p.is_file() or not p.stat().st_size]
    if missing:
        raise Wait(WAIT_REVIEW,
                   f"等待人工核对：请在 {job} 保存 {' 和 '.join(missing)}"
                   f"（对照 review/ 与原谱逐小节校对），然后重跑本命令。")


def do_handoff(a, rt, job):
    wf.handoff(base_ns(a, job=job, fold_multirests=a.fold_multirests), rt)


def do_render(a, rt, job):
    wf.render(base_ns(a, job=job, edition=a.edition, title=a.title, pitch_mode="movable",
                      fixed_tonic="C", template=a.template, instrument=a.instrument,
                      row_gap_mm=a.row_gap_mm, page_start=a.page_start), rt)


def do_export(a, rt, job):
    edition = job / a.edition
    project = edition / "editable.jpwabc"
    if not project.is_file():
        raise Wait(WAIT_EXPORT, f"{edition} 中没有 editable.jpwabc；请先完成 render 阶段。")
    expected = edition / "jpword-export.pdf"
    if not expected.is_file():
        raise Wait(WAIT_EXPORT, EXPORT_INSTRUCTIONS.format(project=project, expected=expected))


def do_audit(a, rt, job):
    edition = job / a.edition
    report = inspect_export(edition / "jpword-export.pdf", job / "reviewed.musicxml",
                            part_id=a.part_id, measures_per_line=a.measures_per_line,
                            page_starts=a.page_start)
    target = edition / "jpword-audit.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    issues = report.get("issues", [])
    pages = sorted({int(p) for p in report.get("observed", {})})
    print(f"审计报告：{target}")
    print(f"页数 {len(pages)}（{pages}）；问题 {len(issues)} 条；"
          f"长休止检查 {len(report.get('rests', []))} 处；pdf_sha256 {report.get('pdf_sha256', '')[:12]}")
    if issues:
        print("未解决问题：" + json.dumps(issues, ensure_ascii=False), file=sys.stderr)
    review = review_path(job, a.edition)
    expected = report.get("pdf_sha256", "")
    if not review.is_file():
        print(f"目检绑定：逐页核对导出后，在 {review} 写入首行「{SHA_PREFIX} {expected}」再定稿。")
    else:
        bound = review_sha(review.read_text(encoding="utf-8-sig"))
        if bound != expected:
            print(f"目检绑定：{review} 记录的 SHA 与本次导出不一致，请按当前导出重新目检并更新该行。")


def do_finalize(a, rt, job):
    edition = job / a.edition
    audit_file = edition / "jpword-audit.json"
    export = edition / "jpword-export.pdf"
    if not audit_file.is_file():
        raise Wait(WAIT_REVIEW, f"{audit_file} 不存在；请先完成 audit 阶段（重跑本命令）。")
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    current_sha = wf.digest(export)
    if audit.get("pdf_sha256") != current_sha:
        raise Wait(WAIT_REVIEW,
                   f"导出已换版：最新 {export.name} 与审计记录哈希不一致。"
                   f"请运行带 --from audit 的同一命令重新审计后再定稿。")
    issues = audit.get("issues", [])
    if issues:
        raise Wait(WAIT_REVIEW,
                   f"版面审计仍有 {len(issues)} 条未解决问题，不能定稿："
                   + json.dumps(issues, ensure_ascii=False)
                   + "；请修订并重新导出后，用 --from audit 续跑。")
    review = review_path(job, a.edition)
    if not review.is_file():
        raise Wait(WAIT_REVIEW,
                   f"缺少逐页目检记录 {review}。请按当前导出逐页核对，"
                   f"在文件首行写入「{SHA_PREFIX} {current_sha}」后重跑本命令。")
    bound = review_sha(review.read_text(encoding="utf-8-sig"))
    if bound != current_sha:
        raise Wait(WAIT_REVIEW,
                   f"{review} 未绑定当前导出：需要首行「{SHA_PREFIX} {current_sha}」"
                   f"（现记录：{bound or '无'}）。请按当前导出重新目检后重跑。")
    if len(review_body(review.read_text(encoding="utf-8-sig"))) < 40:
        raise Wait(WAIT_REVIEW,
                   f"{review} 除哈希行外缺少逐页目检正文（不少于 40 字）。"
                   f"请逐页记录核对结果后再定稿。")
    wf.finalize(base_ns(a, job=job, edition=a.edition, review=review, pdf=export), rt)


class Wait(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


ACTIONS = {"prepare": do_prepare, "review": do_review, "handoff": do_handoff,
           "render": do_render, "jpword-export": do_export, "audit": do_audit,
           "finalize": do_finalize}


def cli():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=HERE / "runtime.local.json")
    p.add_argument("--scratch", type=Path)
    sub = p.add_subparsers(required=True, dest="command")

    run = sub.add_parser("run", help="推进或续跑一条转谱任务")
    run.add_argument("--pdf", type=Path, help="原始五线谱分谱 PDF（首次运行必填）")
    run.add_argument("--job", type=Path, required=True, help="任务目录")
    run.add_argument("--title", help="曲目名称")
    run.add_argument("--template", type=Path, help="JPword UTF-16 模板，提供后生成 editable.jpwabc")
    run.add_argument("--instrument", default=None)
    run.add_argument("--row-gap-mm", type=float)
    run.add_argument("--page-start", action="append", help="JPword 换页行首小节，可重复")
    run.add_argument("--edition", help="默认 edition-01")
    run.add_argument("--draft", type=Path, help="prepare 阶段可选的识谱初稿")
    run.add_argument("--vector-audit", action="store_true")
    run.add_argument("--fold-multirests", action="store_true")
    run.add_argument("--part-id", default="")
    run.add_argument("--measures-per-line", type=int, default=0)
    run.add_argument("--from", dest="from_stage", choices=STAGES,
                     help="从指定阶段重跑（丢弃该阶段及之后的完成记录）")
    run.add_argument("--list", action="store_true", help="只显示任务进度后退出")

    st = sub.add_parser("status", help="显示任务进度")
    st.add_argument("--job", type=Path, required=True)
    a = p.parse_args()

    if a.command == "status":
        state = load_state(a.job.resolve())
        done = set(state.get("done", []))
        print(f"任务：{a.job.resolve()}")
        for stage in STAGES:
            mark = "✓" if stage in done else "…"
            print(f"  {mark} {stage}")
        return

    job = a.job.resolve()
    job.mkdir(parents=True, exist_ok=True)
    state = load_state(job)
    params = state.setdefault("params", {})
    for key in ("title", "template", "instrument", "row_gap_mm", "page_starts", "edition"):
        value = getattr(a, key if key != "page_starts" else "page_start")
        if value is not None:
            params[key] = str(value) if isinstance(value, Path) else value
    save_state(job, state)

    edition = params.get("edition") or "edition-01"
    if not edition or not edition.isascii() or not all(c.isalnum() or c in "-_" for c in edition):
        p.error("--edition 使用英文、数字、连字符或下划线")
    template = params.get("template")
    ns = argparse.Namespace(config=a.config, scratch=a.scratch, pdf=a.pdf, job=job,
                            draft=a.draft, vector_audit=a.vector_audit,
                            fold_multirests=a.fold_multirests, edition=edition,
                            title=params.get("title"),
                            template=Path(template) if template else None,
                            instrument=params.get("instrument", ""),
                            row_gap_mm=params.get("row_gap_mm", 13.0),
                            page_start=params.get("page_starts"),
                            part_id=a.part_id, measures_per_line=a.measures_per_line)

    if a.list:
        done = set(state.get("done", []))
        for stage in STAGES:
            print(("✓ " if stage in done else "… ") + stage)
        return

    done = state.get("done", [])
    if a.from_stage:
        done = done[:done.index(a.from_stage)] if a.from_stage in done else done
        done = [s for s in done if STAGES.index(s) < STAGES.index(a.from_stage)]
    rt = wf.runtime(ns)
    for stage in STAGES:
        if stage in done:
            print(f"跳过已完成：{stage}")
            continue
        print(f"── 阶段：{stage}")
        try:
            ACTIONS[stage](ns, rt, job)
        except Wait as w:
            save_state(job, state)
            print(w, file=sys.stderr)
            sys.exit(w.code)
        done = state["done"] = [*done, stage]
        save_state(job, state)
    print(f"全部阶段完成。定稿：{job / edition / 'delivery'}")


if __name__ == "__main__":
    try:
        cli()
    except (Wait,) as w:
        print(w, file=sys.stderr)
        sys.exit(w.code)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"流程停止：{e}", file=sys.stderr)
        sys.exit(1)
