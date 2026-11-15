"""Windows single-part workflow: raw PDF → reviewed XML → proof → print PDF."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from converter import convert, write_draft
from audit import audit_project
from score_io import load_score, part_measures

HERE = Path(__file__).resolve().parent
VECTOR_OFF = ["--no-vector-keys", "--no-vector-slurs", "--no-vector-tempos",
              "--no-vector-dynamics", "--no-vector-wedges"]


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, payload):
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def runtime(a):
    settings = read_json(a.config)
    if a.scratch is None:
        a.scratch = Path(settings.get('scratch', tempfile.gettempdir()))
    upstream = Path(settings["upstream"]).resolve(strict=True)
    lily = Path(settings["lilypond"]).resolve(strict=True)
    python = Path(settings["python"]).resolve(strict=True)
    return upstream, lily, python, settings["backend"]


def ascii_workspace(root):
    root = root.resolve()
    if not str(root).isascii():
        raise ValueError("当前临时目录含非 ASCII 字符。请用 --scratch 指向可写的英文/数字路径（例如 D:/score-tmp）")
    root.mkdir(parents=True, exist_ok=True)
    return root


def run(runtime, script, *args, cwd=None, scratch=None):
    _, lily, py, _ = runtime
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", LILYPOND=str(lily), LILYPOND_PATH=str(lily))
    if scratch:
        env.update(TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch))
    subprocess.run([str(py), "-B", str(script), *map(str,args)], env=env, cwd=cwd, check=True)


def print_review_template(path):
    path.write_text("# 逐页校对记录\n\n"
                    "- 原谱页码 / 行 / 小节：\n- 原谱与识谱差异、修改和理由：\n"
                    "- 音高 / 八度 / 升降还原 / 时值 / 休止：\n"
                    "- 同音延音 / 连奏 / 连音组 / 跳音▼ / tr / 倚音：\n"
                    "- 速度 / 调拍 / 力度 / 换乐器 / 多小节休止：\n"
                    "- 待确认项目：\n",encoding="utf-8")


def prepare(a, rt):
    upstream,_,_,backend=rt
    pdf=a.pdf.resolve(strict=True)
    if not pdf.is_file() or pdf.suffix.lower()!=".pdf":
        raise ValueError("输入必须是原始五线谱分谱 PDF")
    job=a.job.resolve()
    if job.exists():
        raise FileExistsError("任务目录已存在，请另选新目录")
    job.parent.mkdir(parents=True,exist_ok=True)
    scratch = ascii_workspace(a.scratch)
    with tempfile.TemporaryDirectory(prefix="score-", dir=scratch) as name:
        temp=Path(name)
        staged_input=temp/"input.pdf"
        staged_job=temp/"job"
        shutil.copyfile(pdf,staged_input)
        extras=["--backend",backend]
        if a.draft:
            staged_draft=temp/("draft"+a.draft.suffix)
            shutil.copyfile(a.draft.resolve(strict=True), staged_draft)
            extras+=["--draft",staged_draft]
        if a.vector_audit:
            extras.append("--vector-audit")
        try:
            run(rt,HERE/"score_preflight.py","--repo",upstream,"prepare",staged_input,
                "--job",staged_job,*extras,cwd=temp,scratch=temp)
        except subprocess.CalledProcessError:
            if staged_job.exists():
                shutil.copytree(staged_job,job)
                print(f"识谱失败，已保存诊断：{job}",file=sys.stderr)
            raise
        if digest(staged_job/"source.pdf")!=digest(pdf):
            raise ValueError("原谱指纹不同")
        shutil.copytree(staged_job,job)
    print_review_template(job/"review-template.md")
    print(f"下一步：查看 {job/'review'}，保存 reviewed.musicxml 和 review-notes.md。")


def handoff(a, rt):
    upstream=rt[0]
    job=a.job.resolve(strict=True)
    part_measures(load_score(job/"reviewed.musicxml"))
    args=["--fold-multirests"] if a.fold_multirests else []
    run(rt,HERE/"score_preflight.py","--repo",upstream,"handoff","--job",job,*args)


def checked_handoff(job):
    folder=job/"handoff"
    meta=read_json(folder/"handoff.json")
    files={}
    for k in ("source_pdf","reviewed_musicxml","insitu_musicxml"):
        rel=Path(meta[k])
        if rel.name!=str(rel):
            raise ValueError("交接清单的文件名必须在本目录内")
        path=(folder/rel).resolve(strict=True)
        if not path.is_relative_to(folder.resolve()) or digest(path)!=meta[k+"_sha256"]:
            raise ValueError(f"交接文件已变更：{path.name}；重新校对并生成交接件")
        files[k]=path
    for key in ("source_pdf","reviewed_musicxml"):
        if digest(job/files[key].name)!=meta[key+"_sha256"]:
            raise ValueError(f"任务目录的 {files[key].name} 已变更；重新生成交接件")
    if meta["remaining_timing_flags"]:
        print(f"留有 {meta['remaining_timing_flags']} 条时值疑点，发布前在复核中说明。",file=sys.stderr)
    return files,meta


def pdf_facts(path):
    import pymupdf
    with pymupdf.open(path) as document:
        if not document.page_count or any(not page.get_contents() for page in document):
            raise ValueError(f"PDF 含空页：{path.name}")
        return {"pages":document.page_count,"sha256":digest(path)}


def render(a, rt):
    if a.template and a.pitch_mode != 'movable':
        raise ValueError("JPword 模板分支使用首调。固定调纯简谱请去掉 --template")
    upstream=rt[0]
    job=a.job.resolve(strict=True)
    files,meta=checked_handoff(job)
    output=job/a.edition
    if output.exists():
        raise FileExistsError(f"{output} 已存在，请改用新版本名")
    scratch=ascii_workspace(a.scratch)
    with tempfile.TemporaryDirectory(prefix="score-",dir=scratch) as name:
        stage=Path(name)
        source=stage/"source.pdf"
        master=stage/"reviewed.musicxml"
        insitu=stage/"insitu.musicxml"
        for key,dest in zip(("source_pdf","reviewed_musicxml","insitu_musicxml"),(source,master,insitu),strict=True):
            shutil.copyfile(files[key],dest)
        common=["--title",a.title,"--pitch-mode",a.pitch_mode,"--fixed-tonic",a.fixed_tonic,*VECTOR_OFF]
        converted=stage/"rendered"
        converted.mkdir()
        job_probe=converted/"audit"
        run(rt,upstream/"jianpu.py",source,"--mxl",insitu,"--mode","insitu",
            "--layout","single","--engine","spaced","--work",job_probe,"-o",converted/"alignment",*common,cwd=stage,scratch=stage)
        run(rt,upstream/"jianpu.py",source,"--mxl",master,"--mode","jianpu",
            "--work",job_probe,"-o",converted/"numbered",*common,cwd=stage,scratch=stage)
        proofs={"alignment":pdf_facts(converted/"alignment.insitu.pdf"),"numbered":pdf_facts(converted/"numbered.jianpu.pdf")}
        if a.template:
            score,report=convert(master,a.template.resolve(strict=True),title=a.title,instrument=a.instrument)
            project=converted/"editable.jpwabc"
            write_draft(project,score)
            report.update(project_check=audit_project(master,project))
            write_json(converted/"jpword-draft.json",report)
        write_json(converted/"render.json",{"status":"pending_visual_review","source_pdf_sha256":meta["source_pdf_sha256"],
            "reviewed_musicxml_sha256":meta["reviewed_musicxml_sha256"],"proofs":proofs})
        shutil.copytree(converted,output)
    print(f"校对文件：{output/'alignment.insitu.pdf'}")
    print(f"纯简谱待验稿：{output/'numbered.jianpu.pdf'}")


def finalize(a, rt):
    job=a.job.resolve(strict=True)
    files,meta=checked_handoff(job)
    edition=job/a.edition
    manifest=read_json(edition/"render.json")
    if manifest["reviewed_musicxml_sha256"]!=meta["reviewed_musicxml_sha256"] or manifest["source_pdf_sha256"]!=meta["source_pdf_sha256"]:
        raise ValueError("排版稿来自另一版本，请重排")
    notes=Path(a.review).resolve(strict=True)
    text=notes.read_text(encoding="utf-8-sig")
    if not text.strip() or len(text.strip())<40:
        raise ValueError("请保存逐页复验记录，写清实际核对的页码、符号和仍有的差异")
    pdf=Path(a.pdf).resolve(strict=True) if a.pdf else edition/"numbered.jianpu.pdf"
    facts=pdf_facts(pdf)
    if not a.pdf and facts!=manifest["proofs"]["numbered"]:
        raise ValueError("待验 PDF 已变更，请确认版本并显式传入 --pdf")
    delivery=edition/"delivery"
    delivery.mkdir(exist_ok=False)
    shutil.copyfile(pdf,delivery/"performance.pdf")
    shutil.copyfile(notes,delivery/"print-review.md")
    write_json(delivery/"delivery.json",{"status":"visually_reviewed_by_operator","pdf":facts,
            "reviewed_musicxml_sha256":meta["reviewed_musicxml_sha256"],"review_sha256":digest(notes)})
    print(delivery/"performance.pdf")


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=HERE/"runtime.local.json")
    p.add_argument("--scratch",type=Path)
    sub=p.add_subparsers(required=True,dest="action")
    prep=sub.add_parser("prepare")
    prep.add_argument("pdf",type=Path)
    prep.add_argument("--job",type=Path,required=True)
    prep.add_argument("--draft",type=Path)
    prep.add_argument("--vector-audit",action="store_true")
    h=sub.add_parser("handoff")
    h.add_argument("--job",type=Path,required=True)
    h.add_argument("--fold-multirests",action="store_true")
    r=sub.add_parser("render")
    r.add_argument("--job",type=Path,required=True)
    r.add_argument("--edition",default="edition-01")
    r.add_argument("--title",required=True)
    r.add_argument("--pitch-mode",choices=["movable","fixed"],default="movable")
    r.add_argument("--fixed-tonic",default="C")
    r.add_argument("--template",type=Path,help="可选的 JPword 工程模板")
    r.add_argument("--instrument",default="")
    final=sub.add_parser("finalize")
    final.add_argument("--job",type=Path,required=True)
    final.add_argument("--edition",default="edition-01")
    final.add_argument("--review",type=Path,required=True)
    final.add_argument("--pdf",type=Path,help="可选：人工调整后从 JPword 导出的本版纯简谱 PDF")
    a=p.parse_args()
    edition=getattr(a,"edition","edition-01")
    if not edition or not edition.isascii() or not all(c.isalnum() or c in "-_" for c in edition):
        p.error("--edition 使用英文、数字、连字符或下划线")
    try:
        {"prepare":prepare,"handoff":handoff,"render":render,"finalize":finalize}[a.action](a,runtime(a))
    except (OSError,ValueError,subprocess.CalledProcessError) as e:
        p.exit(1,f"流程停止：{e}\n")


if __name__=="__main__":
    cli()
