#!/usr/bin/env python3
"""
Genera dataset NER italiano tramite Claude API.
Dominio: storia e letteratura italiana.
Output: train.jsonl (18,000 records) + gold.jsonl (900 records).
"""

import html
import json
import os
import math
import re
import random
import time
from collections import Counter
from pathlib import Path

import anthropic

BASE_TRAIN_SIZE = 18000
BASE_GOLD_SIZE = 900
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "8"))
MAX_EFFECTIVE_BATCH_SIZE = int(os.environ.get("MAX_EFFECTIVE_BATCH_SIZE", "6"))
OUTPUT_DIR = Path("/home/aendriu/Para/Project/train-bert")
METADATA_DIR = OUTPUT_DIR / "metadata"

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
# Prefer a Haiku model by default; can be overridden with ANTHROPIC_MODEL env var.
# If the chosen Haiku model is unavailable, the script will surface the error so
# you can set a different model via environment.
MODEL_NAME = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")

if not API_KEY:
    raise RuntimeError("Set ANTHROPIC_API_KEY in the environment before running this script.")

ENTITIES = ["DATE", "PER", "LOC", "ORG", "WORK", "EVENT", "TIT", "FANT", "REL"]

NO_ENTITY_RATIO = 0.10
ENTITY_MIN_COUNT = 3
ENTITY_MAX_COUNT = 4
METADATA_CONTEXT_LIMIT = 16

PROFILE_CYCLE = [
    {"name": "history_core", "labels": ["PER", "DATE", "LOC"], "source": "general_history"},
    {"name": "institutional", "labels": ["PER", "ORG", "DATE"], "source": "metadata_grounded"},
    {"name": "work_and_author", "labels": ["PER", "WORK", "DATE"], "source": "metadata_grounded"},
    {"name": "event_chronicle", "labels": ["EVENT", "DATE", "LOC"], "source": "general_history"},
    {"name": "noble_titles", "labels": ["TIT", "PER", "LOC"], "source": "metadata_grounded"},
    {"name": "fantastic_literary", "labels": ["FANT", "PER", "WORK"], "source": "general_history"},
    {"name": "kinship", "labels": ["REL", "PER", "PER"], "source": "metadata_grounded"},
    {"name": "fantastic_event", "labels": ["FANT", "EVENT", "WORK"], "source": "general_history"},
    {"name": "kinship_titles", "labels": ["REL", "TIT", "PER"], "source": "metadata_grounded"},
    {"name": "mixed_history", "labels": ["PER", "LOC", "ORG", "DATE"], "source": "general_history"},
    {"name": "mixed_literary", "labels": ["PER", "WORK", "EVENT"], "source": "metadata_grounded"},
    {"name": "mixed_authors", "labels": ["PER", "DATE", "WORK", "LOC"], "source": "metadata_grounded"},
]

RARE_SYNTHETIC_LABELS = {"FANT", "REL", "EVENT"}
RARE_SYNTHETIC_PROFILE_CYCLE = [
    profile for profile in PROFILE_CYCLE if any(label in RARE_SYNTHETIC_LABELS for label in profile["labels"])
]
CORE_SYNTHETIC_PROFILE_CYCLE = [
    profile for profile in PROFILE_CYCLE if not any(label in RARE_SYNTHETIC_LABELS for label in profile["labels"])
]
SYNTHETIC_RARE_SLOT_PERIOD = 3

REAL_RATIO = 0.60
SYNTHETIC_RATIO = 0.40
TRAIN_RATIO = 0.90
MAX_BOOK_LABEL_SHARE = 0.02
AVERAGE_LABELS_PER_REAL_RECORD = 3
DEFAULT_DATASET_SCALE = 0.30 if MODEL_NAME.startswith("claude-opus-4") else 1.0
DATASET_SCALE = float(os.environ.get("DATASET_SCALE", str(DEFAULT_DATASET_SCALE)))
TRAIN_SIZE = max(1, int(round(BASE_TRAIN_SIZE * DATASET_SCALE)))
GOLD_SIZE = max(1, int(round(BASE_GOLD_SIZE * DATASET_SCALE)))
REAL_BATCH_SIZE = int(os.environ.get("REAL_BATCH_SIZE", str(BATCH_SIZE)))
SYNTHETIC_BATCH_SIZE = int(os.environ.get("SYNTHETIC_BATCH_SIZE", str(BATCH_SIZE)))
REAL_BATCH_SIZE = min(REAL_BATCH_SIZE, MAX_EFFECTIVE_BATCH_SIZE)
SYNTHETIC_BATCH_SIZE = min(SYNTHETIC_BATCH_SIZE, MAX_EFFECTIVE_BATCH_SIZE)
RANDOM_SEED = 42
REAL_GOLD_BOOK_FRACTION = 0.20

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?;:])\s+(?=[A-ZÀ-Ü\"\(\[])")
TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
YEAR_PATTERN = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")

REAL_CATEGORY_HINTS = {
    "historical": ["PER", "DATE", "LOC", "EVENT"],
    "biographical": ["PER", "WORK", "DATE"],
    "literary": ["WORK", "PER", "TIT"],
    "descriptive": ["PER", "LOC", "DATE"],
}


def estimate_call_count(train_size: int, gold_size: int) -> int:
    target_train_real = int(round(train_size * REAL_RATIO))
    train_synthetic_target = max(0, train_size - target_train_real)
    return (
        math.ceil(target_train_real / REAL_BATCH_SIZE)
        + math.ceil(train_synthetic_target / SYNTHETIC_BATCH_SIZE)
        + math.ceil(gold_size / REAL_BATCH_SIZE)
    )


def normalize_text(text: str) -> str:
    text = strip_html(text)
    text = text.replace("\n", " ")
    text = SPACE_PATTERN.sub(" ", text)
    return text.strip()


def sentence_spans(text: str) -> list[dict]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    pieces = SENTENCE_SPLIT_PATTERN.split(normalized)
    if len(pieces) == 1:
        pieces = re.split(r"(?<=[.!?])\s+", normalized)

    spans = []
    cursor = 0
    for piece in pieces:
        sentence = SPACE_PATTERN.sub(" ", piece.strip(" \t\r\n;:,-"))
        if len(sentence) < 20:
            continue

        start = normalized.find(sentence, cursor)
        if start < 0:
            start = normalized.find(sentence)
        if start < 0:
            continue

        end = start + len(sentence)
        cursor = end
        spans.append({"text": sentence, "start_char": start, "end_char": end})

    if not spans and len(normalized) >= 20:
        spans.append({"text": normalized, "start_char": 0, "end_char": len(normalized)})

    return spans


def score_chunk(text: str) -> float:
    score = min(len(text), 240) / 10.0
    lower = text.lower()
    if YEAR_PATTERN.search(text):
        score += 4.0
    if any(token in lower for token in ("vita", "autore", "poeta", "scrittore", "lettera", "concilio", "storia")):
        score += 2.0
    if re.search(r"\b[A-ZÀ-Ü][a-zà-ü]+\b", text):
        score += 1.0
    if "," in text:
        score += 0.5
    return score


def classify_chunk(text: str) -> tuple[str, list[str]]:
    lower = text.lower()
    if any(token in lower for token in ("figlio", "figlia", "padre", "madre", "sorella", "fratello", "zio", "nonno", "nonna")):
        return "biographical", REAL_CATEGORY_HINTS["biographical"]
    if any(token in lower for token in ("poesia", "poesie", "romanzo", "novella", "teatro", "rime", "canto", "opera", "saggio", "letter")):
        return "literary", REAL_CATEGORY_HINTS["literary"]
    if any(token in lower for token in ("storia", "concilio", "guerra", "battagl", "repubblic", "regno", "impero", "rivoluz", "politic", "vita", "biograf")):
        return "historical", REAL_CATEGORY_HINTS["historical"]
    return "descriptive", REAL_CATEGORY_HINTS["descriptive"]


def load_metadata_books() -> list[dict]:
    books = []
    if not METADATA_DIR.exists():
        return books

    for path in sorted(METADATA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        books.append(
            {
                "identifier": data.get("identifier") or path.stem,
                "title": (data.get("title") or path.stem).strip(),
                "author": extract_author_name(data.get("author")),
                "publication": data.get("publication") or "",
                "date": data.get("date") or "",
                "language": data.get("language") or "",
                "access_url": (data.get("access") or {}).get("url") or "",
                "description": data.get("description") or "",
                "contenuto": data.get("contenuto") or "",
                "internal_description": data.get("internal_description") or [],
                "subject": data.get("subject") or [],
                "path": str(path),
            }
        )

    return books


def extract_author_name(author_field) -> str:
    if isinstance(author_field, dict):
        return (author_field.get("name") or "sconosciuto").strip() or "sconosciuto"
    if isinstance(author_field, str):
        return author_field.strip() or "sconosciuto"
    return "sconosciuto"


def extract_real_candidates(books: list[dict]) -> list[dict]:
    candidates = []
    for book in books:
        sources: list[tuple[str, str]] = []
        if book.get("contenuto"):
            sources.append(("contenuto", book["contenuto"]))
        if book.get("description"):
            sources.append(("description", book["description"]))
        for index, line in enumerate(book.get("internal_description") or []):
            sources.append((f"internal_description[{index}]", line))

        seen_sentences: set[str] = set()

        for source_field, raw_text in sources:
            for span in sentence_spans(raw_text):
                sentence_key = span["text"].casefold()
                if sentence_key in seen_sentences:
                    continue
                seen_sentences.add(sentence_key)
                category, label_hints = classify_chunk(span["text"])
                candidates.append(
                    {
                        "kind": "real",
                        "book": {
                            "identifier": book["identifier"],
                            "title": book["title"],
                            "author": book["author"],
                            "publication": book["publication"],
                            "date": book["date"],
                            "language": book["language"],
                            "access_url": book["access_url"],
                            "path": book["path"],
                            "subject": book.get("subject") or [],
                        },
                        "source_field": source_field,
                        "source_start_char": span["start_char"],
                        "source_end_char": span["end_char"],
                        "sentence": span["text"],
                        "category": category,
                        "label_hints": label_hints,
                        "score": score_chunk(span["text"]),
                    }
                )

    return candidates


def select_real_candidates(candidates: list[dict]) -> list[dict]:
    by_book: dict[str, list[dict]] = {}
    for candidate in candidates:
        book_id = candidate["book"]["identifier"]
        by_book.setdefault(book_id, []).append(candidate)

    for items in by_book.values():
        items.sort(key=lambda item: (-item["score"], len(item["sentence"]), item["source_field"], item["source_start_char"]))

    total_candidates = len(candidates)
    book_label_budget = max(1, int(total_candidates * AVERAGE_LABELS_PER_REAL_RECORD * MAX_BOOK_LABEL_SHARE))
    selected: list[dict] = []
    book_label_counts: dict[str, int] = {}

    for book_id in sorted(by_book):
        for candidate in by_book[book_id]:
            current_labels = book_label_counts.get(book_id, 0)
            estimated_labels = max(1, min(4, len(candidate["label_hints"])))
            if current_labels + estimated_labels > book_label_budget:
                continue
            selected.append(candidate)
            book_label_counts[book_id] = current_labels + estimated_labels

    return selected


def build_real_system_prompt() -> str:
    return (
        "You annotate NER on exact Italian metadata excerpts taken from book records.\n"
        "Keep the sentence exactly as provided. Do not paraphrase, expand, or reorder it.\n"
        "Return only a JSON array. Each object must contain id, sentence, entities, source, book, source_field, source_start_char, source_end_char, source_kind.\n"
        "Annotate every entity that is actually present in the provided sentence.\n"
        "Use non-overlapping character offsets."
    )


def build_synthetic_system_prompt(metadata_context: list[str]) -> str:
    corpus_block = "\n".join(f"- {line}" for line in metadata_context[:METADATA_CONTEXT_LIMIT])
    return f"""You generate synthetic Italian NER training data for historical and literary text.

Domain:
- Historical and literary Italian prose, poetry, letters, chronicles, criticism.
- Use the following corpus anchors as style and topic clues.

Corpus anchors from metadata/:
{corpus_block}

Critical dataset goals:
- Keep the synthetic portion varied and useful for rare labels.
- At least one third of synthetic records must include FANT, REL, or EVENT.
- The remaining two thirds should focus on the other labels and avoid repeating
    the same rare-label pattern too often.
- FANT, REL, EVENT, and TIT must appear often enough to learn them but not
  too much.
- Keep the prose natural and varied.

Allowed entity labels:
- DATE: historical dates and periods
- PER: people, authors, rulers, saints, historical figures
- LOC: cities, regions, kingdoms, seas, countries
- ORG: institutions, courts, orders, republics, churches, academies
- WORK: books, poems, plays, treatises
- EVENT: battles, councils, revolts, voyages, political events
- TIT: noble, clerical, civic, or court titles
- FANT: angels, demons, mythic beings, allegorical creatures
- REL: family or kinship terms, when semantically central

Output rules:
- Return ONLY a JSON array.
- Each array item must have keys: id, sentence, entities, source, book, source_kind.
- For mode == "no_entity", entities must be [] exactly.
- For mode == "entity", include all required_labels and keep entity spans non-overlapping.
- Offsets must be exact character positions in the sentence.
- Never invent malformed JSON.
"""


def build_real_user_prompt(batch_specs: list[dict]) -> str:
    return (
        "Annotate these exact real excerpts. Do not modify the sentence text.\n"
        "Return one JSON array with exactly one object per spec.\n"
        "Specs:\n"
        f"{json.dumps(batch_specs, ensure_ascii=False, indent=2)}"
    )


def build_synthetic_user_prompt(batch_specs: list[dict]) -> str:
    return (
        "Generate one JSON array with exactly one object per spec below.\n"
        "Respect the id, mode, source, and required_labels for each item.\n"
        "Specs:\n"
        f"{json.dumps(batch_specs, ensure_ascii=False, indent=2)}"
    )


def build_synthetic_specs(total_records: int, books: list[dict]) -> list[dict]:
    specs = []
    rare_index = 0
    core_index = 0
    if not books:
        return specs

    for idx in range(total_records):
        use_rare_profile = idx % SYNTHETIC_RARE_SLOT_PERIOD == 0
        if use_rare_profile and RARE_SYNTHETIC_PROFILE_CYCLE:
            profile = RARE_SYNTHETIC_PROFILE_CYCLE[rare_index % len(RARE_SYNTHETIC_PROFILE_CYCLE)]
            rare_index += 1
        else:
            profile_cycle = CORE_SYNTHETIC_PROFILE_CYCLE or PROFILE_CYCLE
            profile = profile_cycle[core_index % len(profile_cycle)]
            core_index += 1
        book = books[idx % len(books)]
        specs.append(
            {
                "id": idx,
                "mode": "entity",
                "source": profile["source"],
                "theme": profile["name"],
                "required_labels": profile["labels"],
                "book": {
                    "identifier": book["identifier"],
                    "title": book["title"],
                    "author": book["author"],
                    "publication": book["publication"],
                    "date": book["date"],
                },
            }
        )

    return specs


def build_dataset_plan() -> tuple[list[dict], list[dict]]:
    books = load_metadata_books()
    candidates = extract_real_candidates(books)
    selected_real = select_real_candidates(candidates)
    return selected_real, books


def strip_html(text: str) -> str:
    if isinstance(text, list):
        text = " ".join(str(item) for item in text if item is not None)
    elif isinstance(text, dict):
        text = " ".join(str(value) for value in text.values() if value is not None)
    elif text is None:
        text = ""
    else:
        text = str(text)

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_metadata_context(limit: int = METADATA_CONTEXT_LIMIT) -> list[str]:
    """Extract a compact corpus summary from metadata/ for grounding prompts."""
    contexts = []
    if not METADATA_DIR.exists():
        return contexts

    files = sorted(METADATA_DIR.glob("*.json"))
    if not files:
        return contexts

    step = max(1, len(files) // limit)
    picked = files[::step][:limit]
    for path in picked:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        title = (data.get("title") or path.stem).strip()
        author = (data.get("author") or {}).get("name") or "sconosciuto"
        description = strip_html(data.get("description") or "")
        contenuto = strip_html(data.get("contenuto") or "")
        if description:
            description = description[:180]
        if not description and contenuto:
            description = contenuto[:180]
        contexts.append(f"{title} / {author}" + (f" - {description}" if description else ""))

    return contexts


def build_record_specs(total_records: int) -> list[dict]:
    """Create a balanced plan that over-samples rare labels and limits negative examples."""
    specs = []
    n_no_entity = max(1, int(total_records * NO_ENTITY_RATIO))

    no_entity_positions = set()
    spacing = total_records / float(n_no_entity)
    for i in range(n_no_entity):
        no_entity_positions.add(int(round(i * spacing)))

    profile_index = 0
    for idx in range(total_records):
        if idx in no_entity_positions:
            specs.append(
                {
                    "id": idx,
                    "mode": "no_entity",
                    "source": "general_history",
                    "theme": "descrizione storica o letteraria senza nomi propri espliciti",
                    "min_entities": 0,
                    "max_entities": 0,
                    "required_labels": [],
                }
            )
            continue

        profile = PROFILE_CYCLE[profile_index % len(PROFILE_CYCLE)]
        profile_index += 1
        specs.append(
            {
                "id": idx,
                "mode": "entity",
                "source": profile["source"],
                "theme": profile["name"],
                "min_entities": ENTITY_MIN_COUNT,
                "max_entities": ENTITY_MAX_COUNT,
                "required_labels": profile["labels"],
            }
        )

    return specs


def build_system_prompt(metadata_context: list[str]) -> str:
    corpus_block = "\n".join(f"- {line}" for line in metadata_context[:METADATA_CONTEXT_LIMIT])
    return f"""You generate high-quality Italian NER training data for historical/literary text.

Domain:
- Historical and literary Italian prose, poetry, letters, chronicles, criticism.
- Base the style on actual corpus metadata, but do not only copy titles from it.

Corpus anchors from metadata/:
{corpus_block}

Critical dataset goals:
- Keep the dataset balanced so the model does not collapse to the O label.
- No more than 10 percent of records may have empty entities.
- Entity-bearing records must usually contain 3 or 4 entities.
- At least one third of synthetic records must include FANT, REL, or EVENT.
- The remaining two thirds should focus on the other labels and stay varied.
- FANT, REL, EVENT, and TIT must be represented often enough to learn them.
- Half of the entity-bearing records should be grounded in metadata anchors.
- The other half must use historically plausible references not directly taken from metadata.
- Mix real historical facts with literary and chronicle-like language.

Allowed entity labels:
- DATE: historical dates and periods
- PER: people, authors, rulers, saints, historical figures
- LOC: cities, regions, kingdoms, seas, countries
- ORG: institutions, courts, orders, republics, churches, academies
- WORK: books, poems, plays, treatises
- EVENT: battles, councils, revolts, voyages, political events
- TIT: noble, clerical, civic, or court titles
- FANT: angels, demons, mythic beings, allegorical creatures
- REL: family or kinship terms, when semantically central

Output rules:
- Return ONLY a JSON array.
- Each array item must have keys: id, sentence, entities, source.
- Do not output tokens; they will be derived locally.
- For mode == "no_entity", entities must be [] exactly.
- For mode == "entity", include all required_labels and keep entity spans non-overlapping.
- Offsets must be exact character positions in the sentence.
- Use contiguous substrings only.
- Keep the prose natural and varied.
- Avoid all-label repetition across the batch.
- If a record asks for a rare label, make it central and unambiguous.
- Never invent malformed JSON.
"""


def build_user_prompt(batch_specs: list[dict]) -> str:
    return (
        "Generate one JSON array with exactly one object per spec below.\n"
        "Respect the id, mode, source, and required_labels for each item.\n"
        "Specs:\n"
        f"{json.dumps(batch_specs, ensure_ascii=False, indent=2)}"
    )


def extract_json_array(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("["):
        return json.loads(text)

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("No JSON array found in model output")


def request_json_array(client: anthropic.Anthropic, *, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int):
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return extract_json_array(response.content[0].text)


def repair_json_array(client: anthropic.Anthropic, *, raw_text: str, system_prompt: str) -> list[dict]:
    repair_prompt = (
        "Fix this malformed output into a valid JSON array only. "
        "Preserve as much content as possible. "
        "Return only the JSON array, with no commentary and no markdown.\n\n"
        f"{raw_text}"
    )
    return request_json_array(
        client,
        model=MODEL_NAME,
        system_prompt=system_prompt,
        user_prompt=repair_prompt,
        temperature=0.0,
        max_tokens=4096,
    )


def request_batch_payload(
    client: anthropic.Anthropic,
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> list[dict]:
    try:
        return request_json_array(
            client,
            model=MODEL_NAME,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def split_and_request_payload(
    client: anthropic.Anthropic,
    *,
    batch: list[dict],
    system_prompt: str,
    build_prompt,
    temperature: float,
    max_tokens: int,
    source_kind: str,
    depth: int = 0,
) -> list[dict]:
    if not batch:
        return []

    user_prompt = build_prompt(batch)
    try:
        return request_batch_payload(
            client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        if len(batch) == 1:
            try:
                response = client.messages.create(
                    model=MODEL_NAME,
                    max_tokens=max(1024, max_tokens // 2),
                    temperature=0.0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return repair_json_array(client, raw_text=response.content[0].text, system_prompt=system_prompt)
            except Exception as repair_exc:
                print(f"❌ {source_kind} record error after repair: {repair_exc}")
                return []

        mid = max(1, len(batch) // 2)
        left = split_and_request_payload(
            client,
            batch=batch[:mid],
            system_prompt=system_prompt,
            build_prompt=build_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            source_kind=source_kind,
            depth=depth + 1,
        )
        right = split_and_request_payload(
            client,
            batch=batch[mid:],
            system_prompt=system_prompt,
            build_prompt=build_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            source_kind=source_kind,
            depth=depth + 1,
        )
        if depth == 0:
            print(f"↳ split {source_kind} batch into {len(batch[:mid])} + {len(batch[mid:])} after parse error: {exc}")
        return left + right


def materialize_records(payload: list[dict], batch: list[dict], source_kind: str) -> list[dict]:
    records: list[dict] = []
    returned_by_id = {int(item["id"]): item for item in payload if isinstance(item, dict) and "id" in item}
    debug = os.environ.get("DEBUG_VALIDATION") == "1"
    first_invalid_logged = False
    
    for spec in batch:
        item = returned_by_id.get(spec["id"])
        if not item:
            continue
        try:
            item = normalize_record(item)
        except Exception as e:
            if debug and not first_invalid_logged:
                print(f"  [DEBUG] normalize_record failed: {e}")
                first_invalid_logged = True
            continue

        if source_kind == "synthetic":
            item["book"] = item.get("book") or {"identifier": "synthetic"}
            item["source_kind"] = "synthetic"
        else:
            item["book"] = spec["book"]
            item["source_field"] = spec["source_field"]
            item["source_start_char"] = spec["source_start_char"]
            item["source_end_char"] = spec["source_end_char"]
            item["source_kind"] = source_kind

        if _validate_record(item, spec):
            records.append(item)
        elif debug and not first_invalid_logged:
            print(f"  [DEBUG] record id={spec.get('id')} failed validation")
            print(f"    sentence: {item.get('sentence', 'MISSING')[:100]}")
            print(f"    entities: {item.get('entities', 'MISSING')}")
            print(f"    required_labels: {spec.get('required_labels', [])}")
            first_invalid_logged = True

    return records


def annotate_batch(
    client: anthropic.Anthropic,
    *,
    batch: list[dict],
    system_prompt: str,
    build_prompt,
    temperature: float,
    max_tokens: int,
    source_kind: str,
) -> list[dict]:
    if not batch:
        return []

    payload = split_and_request_payload(
        client,
        batch=batch,
        system_prompt=system_prompt,
        build_prompt=build_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        source_kind=source_kind,
    )
    records = materialize_records(payload, batch, source_kind)
    if records or len(batch) == 1:
        return records

    mid = max(1, len(batch) // 2)
    left = annotate_batch(
        client,
        batch=batch[:mid],
        system_prompt=system_prompt,
        build_prompt=build_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        source_kind=source_kind,
    )
    right = annotate_batch(
        client,
        batch=batch[mid:],
        system_prompt=system_prompt,
        build_prompt=build_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        source_kind=source_kind,
    )
    print(f"↳ split {source_kind} batch into {len(batch[:mid])} + {len(batch[mid:])} after zero-valid-result batch")
    return left + right


def normalize_record(record: dict) -> dict:
    sentence = record.get("sentence")
    if not isinstance(sentence, str):
        raise ValueError("Missing sentence")

    entities = record.get("entities")
    if not isinstance(entities, list):
        raise ValueError("Missing entities")

    record["sentence"] = re.sub(r"\s+", " ", sentence).strip()
    record["entities"] = entities
    record["source"] = record.get("source") or "synthetic"
    record["tokens"] = record.get("tokens") or record["sentence"].split()
    return record


def _entity_overlaps(a: dict, b: dict) -> bool:
    return not (a["end_char"] <= b["start_char"] or b["end_char"] <= a["start_char"])


def _repair_offsets(sentence: str, entity_label: str, entities: list[dict], idx: int) -> bool:
    """Attempt to find entity by substring match and fix offset. Returns True if fixed."""
    ent = entities[idx]
    start = int(ent.get("start_char", -1))
    end = int(ent.get("end_char", -1))
    
    # Offset already valid
    if start >= 0 and end > start and end <= len(sentence):
        return False
    
    # Try to find label in entity text or nearby
    entity_text = ent.get("text", "")
    if not entity_text:
        return False
    
    # Search for the entity text as a substring
    lower_entity = entity_text.lower().strip()
    lower_sentence = sentence.lower()
    idx_found = lower_sentence.find(lower_entity)
    if idx_found != -1:
        ent["start_char"] = idx_found
        ent["end_char"] = idx_found + len(entity_text)
        return True
    
    return False


def _validate_record(record: dict, spec: dict) -> bool:
    try:
        sentence = record["sentence"]
        entities = record["entities"]
        if not isinstance(sentence, str) or len(sentence) < 20:
            return False
        if not isinstance(entities, list):
            return False

        if spec["mode"] == "no_entity":
            return len(entities) == 0

        min_entities = spec.get("min_entities", len(spec.get("required_labels", [])))
        max_entities = spec.get("max_entities", max(min_entities, len(spec.get("required_labels", [])) + 2))
        if not (min_entities <= len(entities) <= max_entities):
            return False

        # Try to repair offsets before validation
        for idx in range(len(entities)):
            ent = entities[idx]
            start = int(ent.get("start_char", -1))
            end = int(ent.get("end_char", -1))
            if start < 0 or end > len(sentence) or start >= end:
                _repair_offsets(sentence, ent.get("label"), entities, idx)

        seen_labels = []
        last_entity = None
        for ent in sorted(entities, key=lambda item: (int(item.get("start_char", 0)), int(item.get("end_char", 0)))):
            label = ent.get("label")
            start = int(ent.get("start_char", -1))
            end = int(ent.get("end_char", -1))

            if label not in ENTITIES:
                return False
            if start < 0 or end > len(sentence) or start >= end:
                return False

            entity_text = sentence[start:end]
            if not entity_text.strip():
                return False

            if last_entity and _entity_overlaps(last_entity, ent):
                return False
            last_entity = ent
            seen_labels.append(label)

        # Require at least one of the requested labels to be present
        has_required_label = any(label in seen_labels for label in spec["required_labels"])
        if not has_required_label:
            return False

        return True
    except Exception:
        return False


def build_real_split(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split real candidates by book so gold does not overlap train sources."""
    by_book: dict[str, list[dict]] = {}
    for candidate in candidates:
        book_id = candidate["book"]["identifier"]
        by_book.setdefault(book_id, []).append(candidate)

    book_ids = sorted(by_book)
    rng = random.Random(RANDOM_SEED)
    rng.shuffle(book_ids)

    gold_book_count = max(1, int(round(len(book_ids) * REAL_GOLD_BOOK_FRACTION)))
    gold_books = set(book_ids[:gold_book_count])

    gold_candidates: list[dict] = []
    train_candidates: list[dict] = []
    for book_id, items in by_book.items():
        if book_id in gold_books:
            gold_candidates.extend(items)
        else:
            train_candidates.extend(items)

    if not gold_candidates:
        return candidates, []

    return train_candidates, gold_candidates


def annotate_real_candidates(client: anthropic.Anthropic, specs: list[dict], source_kind: str) -> list[dict]:
    records: list[dict] = []
    for i in range(0, len(specs), REAL_BATCH_SIZE):
        batch = specs[i : i + REAL_BATCH_SIZE]
        system_prompt = build_real_system_prompt()
        print(f"🔧 Annotating {source_kind} batch {i}..{i+len(batch)-1}")
        records.extend(
            annotate_batch(
                client,
                batch=batch,
                system_prompt=system_prompt,
                build_prompt=build_real_user_prompt,
                temperature=0.0,
                max_tokens=4096,
                source_kind=source_kind,
            )
        )

        time.sleep(0.5)

    return records


def annotate_synthetic_records(client: anthropic.Anthropic, specs: list[dict], metadata_context: list[str]) -> list[dict]:
    records: list[dict] = []
    for i in range(0, len(specs), SYNTHETIC_BATCH_SIZE):
        batch = specs[i : i + SYNTHETIC_BATCH_SIZE]
        system_prompt = build_synthetic_system_prompt(metadata_context)
        print(f"🧪 Generating synthetic batch {i}..{i+len(batch)-1}")
        records.extend(
            annotate_batch(
                client,
                batch=batch,
                system_prompt=system_prompt,
                build_prompt=build_synthetic_user_prompt,
                temperature=0.1,
                max_tokens=4096,
                source_kind="synthetic",
            )
        )

        time.sleep(0.5)

    return records


def generate_records(n_records: int) -> tuple[list[dict], list[dict]]:
    """Generate train and gold records with a book-disjoint real holdout."""
    client = anthropic.Anthropic(api_key=API_KEY)
    metadata_context = load_metadata_context()

    # Build real + synthetic pools
    real_candidates, books = build_dataset_plan()
    train_real_candidates, gold_real_candidates = build_real_split(real_candidates)

    target_train_real = int(round(TRAIN_SIZE * REAL_RATIO))
    train_real_candidates = sorted(train_real_candidates, key=lambda x: -x["score"])
    gold_real_candidates = sorted(gold_real_candidates, key=lambda x: -x["score"])

    train_real_candidates = train_real_candidates[:min(target_train_real, len(train_real_candidates))]
    gold_real_candidates = gold_real_candidates[:min(GOLD_SIZE, len(gold_real_candidates))]

    train_synthetic_target = max(0, TRAIN_SIZE - len(train_real_candidates))
    train_synthetic_specs = build_synthetic_specs(train_synthetic_target, books)

    print(f"🧭 Metadata anchors: {len(metadata_context)}")
    print(f"📚 Real candidates available: {len(real_candidates)}")
    print(f"📚 Train real selected: {len(train_real_candidates)}")
    print(f"📚 Gold real selected: {len(gold_real_candidates)}")
    if len(gold_real_candidates) < GOLD_SIZE:
        print(f"⚠️  Gold target reduced from {GOLD_SIZE} to {len(gold_real_candidates)}: not enough disjoint real excerpts are available.")
    print(f"🤖 Model: {MODEL_NAME}")

    real_specs = []
    for idx, cand in enumerate(train_real_candidates):
        real_specs.append({
            "id": idx,
            "mode": "entity",
            "sentence": cand["sentence"],
            "book": cand["book"],
            "source_field": cand["source_field"],
            "source_start_char": cand["source_start_char"],
            "source_end_char": cand["source_end_char"],
            "required_labels": cand["label_hints"],
        })

    gold_specs = []
    for idx, cand in enumerate(gold_real_candidates):
        gold_specs.append({
            "id": idx,
            "mode": "entity",
            "sentence": cand["sentence"],
            "book": cand["book"],
            "source_field": cand["source_field"],
            "source_start_char": cand["source_start_char"],
            "source_end_char": cand["source_end_char"],
            "required_labels": cand["label_hints"],
        })

    train_records = annotate_real_candidates(client, real_specs, "train metadata")
    train_records.extend(annotate_synthetic_records(client, train_synthetic_specs, metadata_context))
    gold_records = annotate_real_candidates(client, gold_specs, "gold metadata")

    rng = random.Random(RANDOM_SEED)
    rng.shuffle(train_records)
    rng.shuffle(gold_records)

    print(f"\n✅ Generati {len(train_records)} train record e {len(gold_records)} gold record")
    return train_records, gold_records


def save_dataset(train_records: list[dict], gold_records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    train_file = OUTPUT_DIR / "train.jsonl"
    with open(train_file, "w", encoding="utf-8") as f:
        for rec in train_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✅ Salvati {len(train_records)} record in {train_file}")

    gold_file = OUTPUT_DIR / "gold.jsonl"
    with open(gold_file, "w", encoding="utf-8") as f:
        for rec in gold_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✅ Salvati {len(gold_records)} record in {gold_file}")


def main():
    print("=" * 70)
    print("🚀 GENERAZIONE DATASET NER ITALIANO VIA CLAUDE API")
    print("=" * 70)
    print(f"📊 Target: {TRAIN_SIZE} train + {GOLD_SIZE} gold = {TRAIN_SIZE + GOLD_SIZE} total")
    print("🌍 Domain: Storia e Letteratura Italiana")
    print(f"📦 Batch size: {BATCH_SIZE} record per API call")
    print(f"⚙️  Dataset scale: {DATASET_SCALE:.2f}")
    print(f"🧮 Estimated API calls: {estimate_call_count(TRAIN_SIZE, GOLD_SIZE)}")
    print(f"⚖️  Negative examples: {int(NO_ENTITY_RATIO * 100)}%")
    print(f"🧠 Rare-label boost: FANT / REL / EVENT / TIT over-sampled")
    print()

    total_records_needed = TRAIN_SIZE + GOLD_SIZE
    train_records, gold_records = generate_records(total_records_needed)

    if len(train_records) < TRAIN_SIZE:
        print(f"⚠️  Generati solo {len(train_records)} train record su {TRAIN_SIZE}; salvo comunque i file parziali.")

    if not gold_records:
        print("⚠️  Generati 0 gold record; salvo comunque i file parziali (gold vuoto).")

    # Save whatever we have (slicing will be shorter if not enough records)
    save_dataset(train_records[:TRAIN_SIZE], gold_records)

    print("\n" + "=" * 70)
    print("✅ DATASET GENERATO CON SUCCESSO!")
    print("=" * 70)
    print(f"Train: {OUTPUT_DIR / 'train.jsonl'}")
    print(f"Gold:  {OUTPUT_DIR / 'gold.jsonl'}")
    print("\n🎯 Prossimo passo: python train.py")


if __name__ == "__main__":
    main()
