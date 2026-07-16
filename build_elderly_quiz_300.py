import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path


CANONICAL_INPUT = Path("elderly_health_question_source.json")
OUTPUT = Path("quiz_question_20260714_elderly_300.json")
EXPECTED_COUNT = 300
SHUFFLE_SEED = 20260716
UPDATED_AT = "2026-07-16 18:00:00"
SOURCE_TYPE = "ELDERLY_HEALTH_300_V2"

OPTION_KEYS = ["A", "B", "C", "D"]
DIFFICULTY_VALUES = {1: "EASY", 2: "NORMAL", 3: "NORMAL"}

# These phrases are strong signals that an option is filler rather than a
# plausible misconception. Keep this list narrow so legitimate teaching
# examples are not rejected.
BANNED_FILLER_PHRASES = {
    "让药片更漂亮",
    "替代睡眠",
    "增加营养摄入",
    "治疗关节痛",
    "送给邻居处理",
}


def normalize_text(value):
    return re.sub(r"[\s，。！？；：、,.!?;:]", "", value).lower()


def semantic_fingerprint(category, question, correct):
    payload = f"{category}|{question}|{correct}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def extract_content(row):
    options = row.get("options_json", [])
    option_by_key = {option.get("key"): option.get("text", "").strip() for option in options}
    correct_key = row.get("correct_option")
    if correct_key not in option_by_key:
        raise SystemExit(f"Question {row.get('id')} has no matching correct option")

    correct = option_by_key[correct_key]
    wrongs = sorted(
        [option_by_key[key] for key in OPTION_KEYS if key != correct_key],
        key=normalize_text,
    )
    return {
        "id": row["id"],
        "category": row["category"].strip(),
        "tags": list(row.get("tags_json", [])),
        "level": int(row["difficulty_level"]),
        "question": row["question_text"].strip(),
        "correct": correct,
        "wrongs": wrongs,
        "explanation": row.get("explanation", "").strip(),
        "reference_source": row.get("reference_source") or row.get("source_text", ""),
        "quality_score": int(row.get("quality_score", 0)),
        "risk_level": int(row.get("risk_level", 1)),
        "created_at": row.get("created_at", "2026-07-14 10:00:00"),
    }


def validate_content(items):
    if len(items) != EXPECTED_COUNT:
        raise SystemExit(f"Expected {EXPECTED_COUNT} questions, got {len(items)}")

    expected_ids = list(range(1, EXPECTED_COUNT + 1))
    actual_ids = [item["id"] for item in items]
    if actual_ids != expected_ids:
        raise SystemExit("Question ids must be sequential from 1 to 300")

    question_counts = Counter(normalize_text(item["question"]) for item in items)
    duplicate_questions = [text for text, count in question_counts.items() if count > 1]
    if duplicate_questions:
        raise SystemExit(f"Duplicate question text detected: {duplicate_questions[:5]}")

    for item in items:
        qid = item["id"]
        if item["level"] not in DIFFICULTY_VALUES:
            raise SystemExit(f"Question {qid} has invalid difficulty level")
        if not item["question"].endswith(("？", "?")):
            raise SystemExit(f"Question {qid} must end with a question mark")
        if not item["explanation"]:
            raise SystemExit(f"Question {qid} has no explanation")
        if len(item["wrongs"]) != 3:
            raise SystemExit(f"Question {qid} must have exactly three distractors")

        option_texts = [item["correct"], *item["wrongs"]]
        normalized_options = [normalize_text(text) for text in option_texts]
        if any(not text for text in normalized_options):
            raise SystemExit(f"Question {qid} has an empty option")
        if len(set(normalized_options)) != 4:
            raise SystemExit(f"Question {qid} has duplicate or near-duplicate options")

        filler = [phrase for phrase in BANNED_FILLER_PHRASES if phrase in "|".join(item["wrongs"])]
        if filler:
            raise SystemExit(f"Question {qid} contains filler distractors: {filler}")


def correct_position_schedule(count):
    if count % 4:
        raise SystemExit("Question count must be divisible by four for balanced answer positions")

    target_per_position = count // 4
    for attempt in range(1000):
        rng = random.Random(SHUFFLE_SEED + attempt)
        remaining = [target_per_position] * 4
        positions = []
        while len(positions) < count:
            candidates = [position for position, left in enumerate(remaining) if left]
            if len(positions) >= 2 and positions[-1] == positions[-2]:
                candidates = [position for position in candidates if position != positions[-1]]
            if not candidates:
                break
            weights = [remaining[position] for position in candidates]
            chosen = rng.choices(candidates, weights=weights, k=1)[0]
            positions.append(chosen)
            remaining[chosen] -= 1
        if len(positions) == count and positions != [index % 4 for index in range(count)]:
            return positions
    raise SystemExit("Unable to create a balanced non-patterned answer schedule")


def ordered_options(item, correct_position):
    seed_text = f"{SHUFFLE_SEED}|{item['id']}|{item['question']}"
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    wrongs = item["wrongs"][:]
    random.Random(seed).shuffle(wrongs)
    wrongs.insert(correct_position, item["correct"])
    return [
        {"key": key, "text": text}
        for key, text in zip(OPTION_KEYS, wrongs)
    ]


def build_rows(items):
    positions = correct_position_schedule(len(items))
    rows = []
    for item, correct_position in zip(items, positions):
        options = ordered_options(item, correct_position)
        correct_option = OPTION_KEYS[correct_position]
        reference_source = item["reference_source"]
        rows.append(
            {
                "id": item["id"],
                "status": "ENABLED",
                "category": item["category"],
                "tags_json": item["tags"],
                "use_count": 0,
                "created_at": item["created_at"],
                # Downstream compatibility keeps the historical EASY/NORMAL
                # enum; difficulty_level remains the authoritative 1/2/3 value.
                "difficulty": DIFFICULTY_VALUES[item["level"]],
                "risk_level": item["risk_level"],
                "updated_at": UPDATED_AT,
                "explanation": item["explanation"],
                "source_text": reference_source,
                "source_type": SOURCE_TYPE,
                "wrong_count": 0,
                "options_json": options,
                "correct_count": 0,
                "quality_score": item["quality_score"],
                "question_text": item["question"],
                "correct_option": correct_option,
                "difficulty_level": item["level"],
                "reference_source": reference_source,
                "semantic_fingerprint": semantic_fingerprint(
                    item["category"], item["question"], item["correct"]
                ),
            }
        )
    return rows


def validate_rows(rows):
    position_counts = Counter(row["correct_option"] for row in rows)
    if position_counts != Counter({key: 75 for key in OPTION_KEYS}):
        raise SystemExit(f"Answer positions are not balanced: {position_counts}")

    actual_positions = [OPTION_KEYS.index(row["correct_option"]) for row in rows]
    if actual_positions == [index % 4 for index in range(len(rows))]:
        raise SystemExit("Answer positions still follow the A/B/C/D cycle")

    fingerprint_counts = Counter(row["semantic_fingerprint"] for row in rows)
    if any(count > 1 for count in fingerprint_counts.values()):
        raise SystemExit("Duplicate semantic fingerprints detected")

    correct_is_longest = 0
    correct_chars = 0
    wrong_chars = 0
    for row in rows:
        option_by_key = {option["key"]: option["text"] for option in row["options_json"]}
        correct = option_by_key[row["correct_option"]]
        wrongs = [text for key, text in option_by_key.items() if key != row["correct_option"]]
        expected_fp = semantic_fingerprint(row["category"], row["question_text"], correct)
        if expected_fp != row["semantic_fingerprint"]:
            raise SystemExit(f"Question {row['id']} has a stale semantic fingerprint")
        correct_chars += len(correct)
        wrong_chars += sum(map(len, wrongs)) / 3
        if len(correct) > max(map(len, wrongs)):
            correct_is_longest += 1

    print(
        "Quality indicators: "
        f"correct-longest={correct_is_longest}/{len(rows)}, "
        f"avg-correct={correct_chars / len(rows):.1f}, "
        f"avg-distractor={wrong_chars / len(rows):.1f}, "
        f"positions={dict(position_counts)}"
    )


def build():
    source_rows = json.loads(CANONICAL_INPUT.read_text(encoding="utf-8"))
    items = [extract_content(row) for row in source_rows]
    validate_content(items)
    rows = build_rows(items)
    validate_rows(rows)
    OUTPUT.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT} with {len(rows)} questions from {CANONICAL_INPUT}")


if __name__ == "__main__":
    build()
