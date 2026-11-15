"""Check the original CC0 fixture against actual OMR, then restore its source tempo."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

# Pitches and lengths in eighth notes, transcribed from staff.ly.
EXPECTED = (
    "G4/2 A4/2 B4/2 D5/2",
    "C5/2 B4/2 A4/4",
    "B4/1 C5/1 D5/1 B4/1 A4/2 G4/2",
    "F#4/2 G4/2 rest/4",
    "G4/3 A4/1 B4/2 C5/2",
    "D5/2 E5/2 D5/2 B4/2",
    "A4/1 B4/1 C5/1 A4/1 G4/2 F#4/2",
    "G4/8",
)


def inspect(measures):
    divisions = 1
    for measure in measures:
        divisions = int(measure.findtext("attributes/divisions", str(divisions)))
        events = []
        for note in measure.findall("note"):
            pitch = note.find("pitch")
            name = "rest"
            if pitch is not None:
                accidental = {"-1": "b", "0": "", "1": "#"}[pitch.findtext("alter", "0")]
                name = pitch.findtext("step") + accidental + pitch.findtext("octave")
            units, remainder = divmod(int(note.findtext("duration")) * 2, divisions)
            if remainder:
                raise ValueError(f"Unexpected duration in measure {measure.get('number')}")
            events.append(f"{name}/{units}")
        yield " ".join(events)


def review(job):
    tree = ET.parse(job / "omr.raw.musicxml")
    root = tree.getroot()
    parts = root.findall("part")
    if len(parts) != 1:
        raise ValueError(f"Expected one part, got {len(parts)}")
    measures = parts[0].findall("measure")
    observed = tuple(inspect(measures))
    if observed != EXPECTED:
        raise ValueError(f"OMR differs from source: {observed!r}")
    if [m.get("number") for m in measures] != list(map(str, range(1, 9))):
        raise ValueError("Unexpected measure labels")
    first = measures[0]
    signature = [first.findtext(f"attributes/{tag}") for tag in ("key/fifths", "time/beats", "time/beat-type")]
    if signature != ["1", "4", "4"]:
        raise ValueError(f"Unexpected signature: {signature}")
    breaks = [m.get("number") for m in measures if m.find("print[@new-system='yes']") is not None]
    if breaks != ["5"]:
        raise ValueError(f"Unexpected line breaks: {breaks}")
    if not first.findall(".//metronome"):
        direction = ET.fromstring(
            '<direction placement="above"><direction-type><metronome>'
            '<beat-unit>quarter</beat-unit><per-minute>84</per-minute>'
            '</metronome></direction-type><sound tempo="84"/></direction>'
        )
        first.insert(list(first).index(first.find("note")), direction)
    elif first.findtext(".//metronome/per-minute") != "84":
        raise ValueError("Unexpected source tempo")
    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    title = work.find("work-title")
    if title is None:
        title = ET.SubElement(work, "work-title")
    title.text = "Windows Etude"
    with (job / "reviewed.musicxml").open("xb") as output:
        tree.write(output, encoding="utf-8", xml_declaration=True)
    with (job / "review-notes.md").open("x", encoding="utf-8") as output:
        output.write("# Source review\n\nPage 1, rows 1–2, measures 1–8. Checked 30 pitches, "
                     "their durations, one half rest, G major, 4/4 and the break before m5 "
                     "against the staff fixture. Restored quarter note = 84 from the source.\n")
    print("Source verified: 8 measures, 30 pitches, 1 rest, 2 systems.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    review(parser.parse_args().job)
