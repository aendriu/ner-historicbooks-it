import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Iterable

# Default sizing constants for chunking
# MAX_CHARS allineato a MAX_INPUT_CHARS del modello (categories.py)
# per evitare troncamento silenzioso in fase di inferenza.
DEFAULT_MIN_CHARS = 500
DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 200


HEADING_PATTERNS = [
    r"^(?:capitolo|canto|atto|scena|libro|parte|sezione)\b\s*[\w\-–—\.]*(?:\s*[ivxlcdm0-9]+)?\s*$",
    r"^(?:sonetto|ode|canzo?ne)\b\s*[\w\-–—\.]*(?:\s*[ivxlcdm0-9]+)?\s*$",
]


def compile_heading_regex() -> re.Pattern:
    pats = [f"({p})" for p in HEADING_PATTERNS]
    rx = re.compile("|".join(pats), re.IGNORECASE | re.MULTILINE)
    return rx


@dataclass
class Section:
    start: int
    end: int
    heading: Optional[str]


@dataclass
class Paragraph:
    start: int
    end: int
    text: str


@dataclass
class Chunk:
    start: int
    end: int
    text: str
    heading: Optional[str]
    section_index: int
    para_start_index: int
    para_end_index: int


def find_sections(text: str) -> List[Section]:
    rx = compile_heading_regex()
    matches = list(rx.finditer(text))
    if not matches:
        return [Section(0, len(text), None)]
    sections: List[Section] = []
    for i, m in enumerate(matches):
        start = m.start()
        # Heading is the full matched line
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", start)
        if line_end == -1:
            line_end = len(text)
        heading = text[line_start:line_end].strip()
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(Section(line_end + 1 if line_end + 1 <= len(text) else line_end, next_start, heading))
    return sections


def split_paragraphs(text: str, base_offset: int = 0) -> List[Paragraph]:
    paras: List[Paragraph] = []
    pos = 0
    # Normalize line endings but keep indices stable relative to given text
    parts = re.split(r"\n{2,}", text)
    cursor = 0
    for part in parts:
        # Find the part within text starting at cursor
        idx = text.find(part, cursor)
        if idx == -1:
            continue
        start = base_offset + idx
        end = start + len(part)
        paras.append(Paragraph(start=start, end=end, text=part.strip()))
        # Advance cursor: part + the blank lines between
        cursor = idx + len(part)
        # Skip following blank lines (already split on them)
        while cursor < len(text) and text[cursor] == "\n":
            cursor += 1
    # Filter empty paragraphs
    return [p for p in paras if p.text]


def sentence_split_ranges(text: str, base_offset: int, min_chars: int, max_chars: int) -> List[Tuple[int, int]]:
    # Find sentence boundaries on punctuation followed by space/newline
    # Keep simple but robust for OCR: . ! ? followed by whitespace or end
    # Match sentence end punctuation possibly followed by quotes/brackets/space
    ends = [m.end() for m in re.finditer(r"[\.\!\?][\"'”’\)\]\s]*", text)]
    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < len(text):
        target_end = min(start + max_chars, len(text))
        # Prefer the last boundary before target_end, but after min_chars
        candidates = [e for e in ends if e > start + min_chars and e <= target_end]
        if candidates:
            end_local = candidates[-1]
        else:
            # If no boundary, try any boundary after min_chars up to +1.5x max
            candidates2 = [e for e in ends if e > start + min_chars and e <= min(start + int(max_chars * 1.5), len(text))]
            end_local = candidates2[-1] if candidates2 else target_end
        abs_start = base_offset + start
        abs_end = base_offset + end_local
        # Avoid zero-length
        if abs_end > abs_start:
            ranges.append((abs_start, abs_end))
        start = end_local
    return ranges


def sliding_windows_on_text(start: int, end: int, max_chars: int, overlap_chars: int) -> List[Tuple[int, int]]:
    windows: List[Tuple[int, int]] = []
    if start >= end:
        return windows
    # Ensure sensible stride
    stride = max(1, max_chars - max(0, overlap_chars))
    s = start
    while s < end:
        e = min(s + max_chars, end)
        windows.append((s, e))
        if e >= end:
            break
        # Step back by overlap to ensure overlap
        s = e - max(0, overlap_chars)
    return windows


def window_units(units: List[Tuple[int, int]], min_chars: int, max_chars: int, overlap_chars: int) -> List[Tuple[int, int]]:
    """Build windowed (start,end) char ranges from atomic units with overlap.
    units: list of (start_char, end_char)."""
    windows: List[Tuple[int, int]] = []
    i = 0
    n = len(units)
    while i < n:
        start_char = units[i][0]
        j = i
        end_char = units[j][1]
        while j < n and ((end_char - start_char) < min_chars or (units[j][1] - start_char) <= max_chars):
            end_char = units[j][1]
            j += 1
        if j == i:
            j = i + 1
            end_char = units[i][1]
        windows.append((start_char, end_char))
        if overlap_chars > 0:
            target = end_char - overlap_chars
            next_i = i
            while next_i < j and units[next_i][1] <= target:
                next_i += 1
            # Clamp to ensure actual overlap: stay within current window
            if next_i >= j:
                next_i = max(i + 1, j - 1)
            if next_i <= i:
                next_i = i + 1
            i = next_i
        else:
            i = j
    return windows


def group_paragraphs(
    paras: List[Paragraph],
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> List[Tuple[int, int]]:
    groups: List[Tuple[int, int]] = []
    i = 0
    n = len(paras)
    while i < n:
        start_char = paras[i].start
        j = i
        end_char = paras[j].end
        while j < n and ((end_char - start_char) < min_chars or ((paras[j].end - start_char) <= max_chars)):
            end_char = paras[j].end
            j += 1
        if j == i:
            j = i + 1
            end_char = paras[i].end
        groups.append((i, j - 1))
        if overlap_chars > 0:
            target = end_char - overlap_chars
            next_i = i
            while next_i < j and paras[next_i].end <= target:
                next_i += 1
            # Clamp to ensure actual overlap: stay within current group
            if next_i >= j:
                next_i = max(i + 1, j - 1)
            if next_i <= i:
                next_i = i + 1
            i = next_i
        else:
            i = j
    return groups


def make_chunks(
    text: str,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    sections = find_sections(text)
    for s_idx, sec in enumerate(sections):
        sec_text = text[sec.start:sec.end]
        paras = split_paragraphs(sec_text, base_offset=sec.start)
        # If no paragraphs, or a single paragraph longer than max, use sentence splitting with overlap
        if not paras or (len(paras) == 1 and (paras[0].end - paras[0].start) > max_chars):
            sent_units = sentence_split_ranges(sec_text, base_offset=sec.start, min_chars=min_chars, max_chars=max_chars)
            wins = window_units(sent_units, min_chars=min_chars, max_chars=max_chars, overlap_chars=overlap_chars)
            # If windows are adjacent (no overlap), enforce overlap via char-level sliding on the section
            if overlap_chars > 0 and len(wins) >= 2 and (wins[0][1] - wins[1][0]) <= 0:
                wins = sliding_windows_on_text(sec.start, sec.end, max_chars=max_chars, overlap_chars=overlap_chars)
            for rs, re_ in wins:
                chunk_text = text[rs:re_].strip()
                if chunk_text:
                    chunks.append(Chunk(start=rs, end=re_, text=chunk_text, heading=sec.heading,
                                        section_index=s_idx, para_start_index=0, para_end_index=0))
            continue

        groups = group_paragraphs(paras, min_chars=min_chars, max_chars=max_chars, overlap_chars=overlap_chars)
        for g_start, g_end in groups:
            start = paras[g_start].start
            end = paras[g_end].end
            # If a group exceeds max (e.g., one huge paragraph), split by sentences inside the group with overlap
            if end - start > max_chars:
                sub_units = sentence_split_ranges(text[start:end], base_offset=start, min_chars=min_chars, max_chars=max_chars)
                for rs, re_ in window_units(sub_units, min_chars=min_chars, max_chars=max_chars, overlap_chars=overlap_chars):
                    chunk_text = text[rs:re_].strip()
                    if chunk_text:
                        chunks.append(Chunk(start=rs, end=re_, text=chunk_text, heading=sec.heading,
                                            section_index=s_idx, para_start_index=g_start, para_end_index=g_end))
            else:
                # If overlap is requested but this group is a single paragraph,
                # build overlapped windows at sentence level to ensure real overlap.
                if overlap_chars > 0 and (end - start) > min_chars:
                    sub_units = sentence_split_ranges(text[start:end], base_offset=start, min_chars=min_chars, max_chars=max_chars)
                    if len(sub_units) > 1:
                        for rs, re_ in window_units(sub_units, min_chars=min_chars, max_chars=max_chars, overlap_chars=overlap_chars):
                            chunk_text = text[rs:re_].strip()
                            if chunk_text:
                                chunks.append(Chunk(start=rs, end=re_, text=chunk_text, heading=sec.heading,
                                                    section_index=s_idx, para_start_index=g_start, para_end_index=g_end))
                        continue
                chunk_text = text[start:end].strip()
                chunks.append(Chunk(start=start, end=end, text=chunk_text, heading=sec.heading,
                                    section_index=s_idx, para_start_index=g_start, para_end_index=g_end))
    return chunks


def iter_input_files(input_dir: Path) -> Iterable[Path]:
    for p in sorted(input_dir.glob('*.json')):
        if p.is_file():
            yield p


def load_text_from_json(p: Path) -> Tuple[str, Dict]:
    data = json.loads(p.read_text(encoding='utf-8'))
    text = data.get('contenuto') or ''
    return text, data


def write_chunks_jsonl(out_path: Path, source_rel: str, chunks: List[Chunk], meta: Dict):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        for idx, c in enumerate(chunks):
            rec = {
                'source_file': source_rel,
                'chunk_id': idx,
                'start_char': c.start,
                'end_char': c.end,
                'heading': c.heading,
                'section_index': c.section_index,
                'para_start_index': c.para_start_index,
                'para_end_index': c.para_end_index,
                'text': c.text,
            }
            # Add lightweight metadata if present
            for k in ('title', 'author', 'identifier', 'date', 'language'):
                if k in meta:
                    rec[k] = meta[k]
                elif k == 'author' and isinstance(meta.get('author'), dict):
                    rec['author'] = meta['author'].get('name')
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def process_all(
    input_dir: Path,
    output_dir: Path,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> int:
    count = 0
    for p in iter_input_files(input_dir):
        try:
            text, meta = load_text_from_json(p)
            if not text.strip():
                continue
            chunks = make_chunks(text, min_chars=min_chars, max_chars=max_chars, overlap_chars=overlap_chars)
            rel = p.name
            out_file = output_dir / f"{Path(rel).stem}.chunks.jsonl"
            write_chunks_jsonl(out_file, source_rel=rel, chunks=chunks, meta=meta)
            count += 1
        except Exception as e:
            # Write an error sentinel file for visibility
            err_file = output_dir / f"{p.stem}.error.txt"
            err_file.write_text(str(e), encoding='utf-8')
    return count
