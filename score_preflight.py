"""Prepare and verify the source score for an existing music_translator workflow."""

import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_project(repo):
    repo = repo.resolve()
    if not (repo / 'jianpu.py').is_file() or not (repo / 'core' / 'omr').is_dir():
        raise ValueError(f'找不到 music_translator：{repo}')
    sys.path.insert(0, str(repo))
    import jianpu
    return jianpu


def runtime(jianpu, backend):
    import onnxruntime as ort

    distributions = {}
    for name in ('homr', 'onnxruntime', 'onnxruntime-gpu', 'onnxruntime-directml'):
        try:
            distributions[name] = version(name)
        except PackageNotFoundError:
            pass
    installed_ort = set(distributions) - {'homr'}
    if len(installed_ort) != 1:
        raise ValueError(f'请在当前解释器环境只安装一种 ONNX Runtime：{sorted(installed_ort)}')
    if backend == 'cuda':
        from core.omr.homr_runner import _add_nvidia_cuda_dll_dirs
        _add_nvidia_cuda_dll_dirs()
        if hasattr(ort, 'preload_dlls'):
            ort.preload_dlls()
    available = ort.get_available_providers()
    if backend == 'cuda' and 'CUDAExecutionProvider' not in available:
        raise ValueError(f'当前环境未提供 CUDAExecutionProvider：{available}')
    gpu = None
    if tool := shutil.which('nvidia-smi'):
        try:
            info = subprocess.run([tool, '--query-gpu=name,driver_version', '--format=csv,noheader'],
                                  capture_output=True, text=True, timeout=10)
            if info.returncode == 0:
                gpu = info.stdout.strip().splitlines()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {'packages': distributions, 'available_providers': available, 'nvidia_gpu': gpu,
            'python': sys.executable,
            'project': str(Path(jianpu.__file__).parent)}


def recognize(jianpu, pdf, job, engine, backend):
    status = {}
    work = job / 'omr'
    work.mkdir()
    sessions = []
    status.update(engine=engine, requested_backend=backend if engine == 'homr' else 'audiveris',
                  status='in_progress', sessions=sessions)
    status_path = job / 'omr-runtime.json'
    save_json(status_path, status)
    if engine == 'homr':
        try:
            status.update(runtime(jianpu, backend))
        except Exception as exc:
            status.update(status='failed', error=str(exc))
            save_json(status_path, status)
            raise
        import onnxruntime as ort
        entry = getattr(jianpu, 'omr_to_musicxml', None)
        if entry is None:
            raise ValueError('当前项目没有 Homr 入口。请使用 README 的参考版本，或用 --draft 导入结果。')
        parameters = inspect.signature(entry).parameters
        options = {'backend': backend} if 'backend' in parameters else {'use_gpu': backend == 'cuda'}
        if 'strict' in parameters:
            options['strict'] = True
        original = ort.InferenceSession

        class ObservedSession(original):
            def __init__(self, path_or_bytes, *args, **kwargs):
                super().__init__(path_or_bytes, *args, **kwargs)
                model = Path(path_or_bytes).name if isinstance(path_or_bytes, (str, Path)) else '<bytes>'
                self.observation = {'model': model, 'providers': self.get_providers(), 'executed': False}
                sessions.append(self.observation)

            def run(self, *args, **kwargs):
                result = super().run(*args, **kwargs)
                self.observation['executed'] = True
                return result

            def run_with_iobinding(self, *args, **kwargs):
                result = super().run_with_iobinding(*args, **kwargs)
                self.observation['executed'] = True
                return result

        ort.InferenceSession = ObservedSession
        try:
            score = entry(pdf, work, **options)
            if any(work.rglob('.partial-omr')) or not (work / f'{pdf.stem}.omr-cache.json').is_file():
                raise ValueError(f'Homr 识别或后处理不完整，请检查 {work}')
            status['status'] = 'complete'
        except Exception as exc:
            status.update(status='failed', error=str(exc))
            raise
        finally:
            ort.InferenceSession = original
            executed = [item for item in sessions if item['executed']
                        and item['model'].startswith(('segnet_', 'encoder_', 'decoder_'))]
            status['observed_homr_providers'] = dict(Counter(
                item['providers'][0] if item['providers'] else 'unknown' for item in executed))
            save_json(status_path, status)
    else:
        entry = getattr(jianpu, 'audiveris_to_musicxml', None)
        if entry is None or 'strict' not in inspect.signature(entry).parameters:
            raise ValueError('当前项目没有严格模式 Audiveris 入口。可在 Audiveris 导出后使用 --draft。')
        try:
            score = entry(pdf, work, strict=True)
            status['status'] = 'complete'
        except Exception as exc:
            status.update(status='failed', error=str(exc))
            raise
        finally:
            save_json(status_path, status)
    return score


def read_score(source):
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            container = ET.fromstring(archive.read('META-INF/container.xml'))
            entry = container.find('.//{*}rootfile')
            if entry is None or not entry.get('full-path'):
                raise ValueError(f'MXL 缺少 rootfile：{source}')
            data = archive.read(entry.attrib['full-path'])
    else:
        data = source.read_bytes()
    root = ET.fromstring(data)
    parts = root.findall('part')
    if root.tag != 'score-partwise' or len(parts) != 1 or not parts[0].findall('measure'):
        raise ValueError('当前流程面向单分谱，需要恰好一个含小节的 score-partwise part。')
    return data, root, parts[0].findall('measure')


def inspect_score(source, pdf):
    import pymupdf
    from music21 import stream
    from core.notation.musicxml_wedges import parse_musicxml_compatible

    _, root, elements = read_score(source)
    score = parse_musicxml_compatible(source)
    bars = list(score.parts[0].getElementsByClass(stream.Measure))
    if len(bars) != len(elements):
        raise ValueError(f'MusicXML 读回小节数与 XML 不一致：{len(bars)} vs {len(elements)}')
    warnings = []
    for index, (bar, raw) in enumerate(zip(bars, elements), 1):
        actual = Fraction(bar.duration.quarterLength).limit_denominator()
        expected = Fraction(bar.barDuration.quarterLength).limit_denominator()
        if actual != expected or not raw.findall('note'):
            warnings.append({'index': index, 'number': raw.get('number'),
                             'quarter_notes': str(actual), 'expected': str(expected),
                             'implicit': raw.get('implicit') == 'yes'})
    with pymupdf.open(pdf) as doc:
        source_pages = len(doc)
    return {
        'pdf_pages': source_pages, 'measures': len(bars), 'first_number': elements[0].get('number'),
        'last_number': elements[-1].get('number'),
        'xml_page_starts': [1, *(i for i, el in enumerate(elements[1:], 2)
                                 if el.find("print[@new-page='yes']") is not None)],
        'duration_review': warnings,
        'tuplet_starts': sum(1 for el in root.iter('tuplet') if el.get('type') in ('start', 'startStop')),
        'ratios': dict(Counter(f'{el.findtext("actual-notes")}:{el.findtext("normal-notes")}'
                               for el in root.iter('time-modification'))),
        'words': [el.text or '' for el in root.findall('.//direction-type/words')],
        'multimeasure_rests': [el.text for el in root.iter('multiple-rest')],
    }


def page_evidence(pdf, source, target):
    import pymupdf
    from insitu.align import align_from_files

    _, _, measures = read_score(source)
    target.mkdir()
    with pymupdf.open(pdf) as doc:
        for page in doc:
            scale = min(3, 2800 / max(page.rect.width, page.rect.height))
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(
                target / f'page-{page.number + 1:03d}.png')
        page_count = len(doc)

    starts = [0, *(i for i, elt in enumerate(measures[1:], 1)
                   if elt.find("print[@new-page='yes']") is not None), len(measures)]
    aligned = []
    if len(starts) != page_count + 1:
        try:
            layouts, slices = align_from_files(pdf, source)
            aligned = list(zip(layouts, slices, strict=True))
        except (RuntimeError, ValueError, OSError) as exc:
            save_json(target / 'alignment-error.json', {'error': str(exc)})
    for page in range(1, page_count + 1):
        rows = [(sl, ly) for ly, sl in aligned if ly.staff.page == page and sl.omr_start < sl.omr_end]
        excerpt = ET.Element('review', page=str(page))
        context = ET.SubElement(excerpt, 'inherited-attributes')
        if len(starts) == page_count + 1:
            first, end = starts[page - 1:page + 1]
            breaks = [first, *(i for i in range(first + 1, end)
                               if measures[i].find("print[@new-system='yes']") is not None), end]
            ranges = [(a, b, {'xml-system-on-page': str(i)})
                      for i, (a, b) in enumerate(zip(breaks, breaks[1:]), 1)]
            excerpt.set('alignment', 'xml-page-breaks')
        elif rows:
            ranges = [(sl.omr_start, sl.omr_end, {
                'line-index': str(sl.staff_index + 1), 'pdf-slots': str(sl.pdf_measures),
                'xml-measures': str(sl.omr_measures),
                'top-points': f'{ly.staff.top:.2f}', 'bottom-points': f'{ly.staff.bottom:.2f}'})
                for sl, ly in rows]
            excerpt.set('alignment', 'estimated-pdf-lines')
        else:
            ranges = []
            excerpt.set('alignment', 'unresolved')
        inherited = {}
        for measure in measures[:ranges[0][0]] if ranges else []:
            for attributes in measure.findall('attributes'):
                for el in attributes:
                    if el.tag in ('divisions', 'key', 'time', 'clef'):
                        inherited[el.tag, el.get('number')] = el
        context.extend(inherited.values())
        for start, end, attrs in ranges:
            row = ET.SubElement(excerpt, 'range', attrs)
            for index in range(start, min(end, len(measures))):
                # Carry complete measures, including words, directions and tuplets.
                wrapper = ET.SubElement(row, 'item', {'xml-index': str(index + 1)})
                wrapper.append(ET.fromstring(ET.tostring(measures[index])))
        ET.indent(excerpt, space='  ')
        ET.ElementTree(excerpt).write(target / f'page-{page:03d}.xml',
                                      encoding='utf-8', xml_declaration=True)


def folded_review_xml(source):
    """Collapse only explicitly marked full-bar rests in a separate display copy."""
    _, root, measures = read_score(source)
    part = root.find('part')
    mapping = []
    index = 0
    while index < len(measures):
        measure = measures[index]
        styles = [(attributes, style, rest)
                  for attributes in measure.findall('attributes')
                  for style in attributes.findall('measure-style')
                  for rest in style.findall('multiple-rest')]
        if not styles:
            index += 1
            continue
        number = measure.get('number')
        if len(styles) != 1:
            raise ValueError(f'小节 {number} 含多个多小节休止标记。')
        attributes, style, marker = styles[0]
        count = int(marker.text or '0')
        span = measures[index:index + count]
        notes = [bar.findall('note') for bar in span]
        if (count < 2 or len(span) != count
                or any(len(events) != 1 or events[0].find("rest[@measure='yes']") is None
                       for events in notes)):
            raise ValueError(f'小节 {number} 的 {count} 小节休止无法安全折叠。')
        for offset, (bar, events) in enumerate(zip(span[1:], notes[1:], strict=True), 1):
            note = events[0]
            if (note.findtext('duration') != notes[0][0].findtext('duration')
                    or any(child.tag not in {'rest', 'duration', 'voice', 'type', 'staff'} for child in note)):
                raise ValueError(f'多小节休止含不同节奏或演奏标记：{bar.get("number")}。')
            for item in bar:
                if item is note:
                    continue
                if (item.tag == 'barline' and item.get('location', 'right') == 'right'
                        and offset == count - 1
                        and not any(line.get('location', 'right') == 'right' for line in measure.findall('barline'))):
                    measure.append(deepcopy(item))
                else:
                    raise ValueError(f'多小节休止含需保留的 {item.tag}：{bar.get("number")}。')
            part.remove(bar)
        style.remove(marker)
        if not len(style):
            attributes.remove(style)
        if not len(attributes):
            measure.remove(attributes)
        mapping.append({'start': number, 'end': span[-1].get('number'), 'count': count})
        index += count
    return root, mapping


def handoff(jianpu, job, fold_multirests):
    pdf = job / 'source.pdf'
    xml = job / 'reviewed.musicxml'
    notes = job / 'review-notes.md'
    draft = json.loads((job / 'draft-check.json').read_text(encoding='utf-8'))
    check = inspect_score(xml, pdf)
    pdf_hash = jianpu._sha256_file(pdf)
    if pdf_hash != draft['source_pdf_sha256']:
        raise ValueError('交接用原谱与识谱时的原谱指纹不同。')
    if not notes.is_file() or not notes.read_text(encoding='utf-8-sig').strip():
        raise ValueError('请先保存 review-notes.md，记录复核范围和疑点。')
    xml_hash = jianpu._sha256_file(xml)
    check.update(source_pdf_sha256=pdf_hash, musicxml_sha256=xml_hash)
    destination = job / 'handoff'
    if destination.exists():
        raise FileExistsError(f'交接目录已存在：{destination}。请归档后重试。')
    with tempfile.TemporaryDirectory(prefix='.handoff-', dir=job) as temporary:
        staging = Path(temporary) / 'handoff'
        staging.mkdir()
        shutil.copy2(pdf, staging / pdf.name)
        shutil.copy2(xml, staging / xml.name)
        shutil.copy2(notes, staging / notes.name)
        save_json(staging / 'review-check.json', check)
        layout_xml = xml.name
        mapping = []
        if fold_multirests:
            root, mapping = folded_review_xml(staging / xml.name)
            if mapping:
                layout_xml = 'reviewed.for-insitu.musicxml'
                display_xml = staging / layout_xml
                ET.indent(root)
                ET.ElementTree(root).write(display_xml, encoding='utf-8', xml_declaration=True)
                from insitu.align import align_from_files

                layouts, slices = align_from_files(staging / pdf.name, display_xml)
                if (not layouts or len(layouts) != len(slices)
                        or any(sl.omr_measures != sl.pdf_measures for sl in slices)):
                    raise ValueError('折叠副本仍有谱面格数差异。请先对照原谱复核。')
        save_json(staging / 'handoff.json', {
            'source_pdf': pdf.name, 'source_pdf_sha256': pdf_hash,
            'reviewed_musicxml': xml.name, 'reviewed_musicxml_sha256': xml_hash,
            'insitu_musicxml': layout_xml,
            'insitu_musicxml_sha256': jianpu._sha256_file(staging / layout_xml),
            'folded_rest_spans': mapping, 'remaining_timing_flags': len(check['duration_review']),
            'review_notes': notes.name,
        })
        staging.rename(destination)
    print(f'交接清单：{destination / "handoff.json"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True, help='Folder containing jianpu.py')
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Check local OMR imports and ONNX Runtime provider list')
    doctor.add_argument('--backend', default='cuda', choices=('cuda', 'cpu'))
    prep = commands.add_parser('prepare', help='Recognize PDF or collect evidence for an existing draft')
    prep.add_argument('pdf', type=Path)
    prep.add_argument('--job', type=Path, required=True, help='New staging folder')
    choice = prep.add_mutually_exclusive_group()
    choice.add_argument('--draft', type=Path, help='Reuse an existing MusicXML or MXL draft')
    choice.add_argument('--engine', default='homr', choices=('homr', 'audiveris'))
    prep.add_argument('--backend', default='cuda', choices=('cuda', 'cpu'))
    prep.add_argument('--vector-audit', action='store_true',
                      help='Also collect supported PDF glyph evidence using the upstream project')
    check = commands.add_parser('check', help='Inspect the corrected XML before handing it off')
    check.add_argument('pdf', type=Path)
    check.add_argument('musicxml', type=Path)
    check.add_argument('--report', type=Path, required=True)
    deliver = commands.add_parser('handoff', help='Package the reviewed XML and source PDF')
    deliver.add_argument('--job', type=Path, required=True)
    deliver.add_argument('--fold-multirests', action='store_true',
                         help='Create a separate MusicXML for one slot per engraved multirest')
    args = parser.parse_args()
    jianpu = load_project(args.repo)
    if args.command == 'doctor':
        info = runtime(jianpu, args.backend)
        import homr.main
        import music21
        import pymupdf

        print(json.dumps(info, ensure_ascii=False, indent=2))
        print('实际 GPU 推理以 prepare 生成的 omr-runtime.json 为准。')
        return
    if args.command == 'handoff':
        handoff(jianpu, args.job.resolve(strict=True), args.fold_multirests)
        return
    pdf = args.pdf.resolve(strict=True)
    if pdf.suffix.lower() != '.pdf':
        parser.error('请使用单分谱的原始 PDF。')

    if args.command == 'check':
        xml = args.musicxml.resolve(strict=True)
        if args.report.resolve() in (pdf, xml):
            parser.error('报告路径不能覆盖原 PDF 或 MusicXML。')
        report = inspect_score(xml, pdf)
        report.update(source_pdf_sha256=jianpu._sha256_file(pdf), musicxml_sha256=jianpu._sha256_file(xml))
        save_json(args.report, report)
        print(f"结构检查：{report['pdf_pages']} 页，{report['measures']} 小节，"
              f"{len(report['duration_review'])} 个时值/空小节待查。报告：{args.report.resolve()}")
        return

    job = args.job.resolve()
    pdf_copy = job / 'source.pdf'
    draft = args.draft.resolve(strict=True) if args.draft else None
    job.mkdir(parents=True)
    shutil.copyfile(pdf, pdf_copy)
    recognized = draft or recognize(jianpu, pdf_copy, job, args.engine, args.backend)
    data, _, _ = read_score(recognized)
    xml = job / 'omr.raw.musicxml'
    xml.write_bytes(data)
    report = inspect_score(xml, pdf_copy)
    report.update(source_pdf=str(pdf), source_pdf_sha256=jianpu._sha256_file(pdf_copy),
                  musicxml_sha256=jianpu._sha256_file(xml))
    save_json(job / 'draft-check.json', report)
    page_evidence(pdf_copy, xml, job / 'review')
    if args.vector_audit:
        from core.omr.vector_notehead_audit import audit_pdf_noteheads
        save_json(job / 'vector-audit.json', audit_pdf_noteheads(pdf_copy, xml))
    print(f'校对目录：{job}')
    if (runtime_report := job / 'omr-runtime.json').exists() and args.engine == 'homr':
        sessions = json.loads(runtime_report.read_text(encoding='utf-8'))['sessions']
        homr_cuda = [s['model'] for s in sessions if s['executed']
                    and 'CUDAExecutionProvider' in s['providers']
                    and s['model'].startswith(('segnet_', 'encoder_', 'decoder_'))]
        if args.backend == 'cuda':
            print(f'Homr CUDA 会话读回：{homr_cuda or "未观察到，检查是否回退 CPU"}。')
            print('会话包含 CUDA 不代表每个算子都在 GPU 执行，参照推理日志。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, ImportError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f'前置流程失败：{exc}', file=sys.stderr)
        raise SystemExit(1) from exc
