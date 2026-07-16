import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from string import Template


HEALTH_INPUT = Path("quiz_question_20260714_elderly_300.json")
CARE_INPUT = Path("online_care_question_bank.md")
OUTPUTS = (Path("quiz_review.html"), Path("index.html"))
CARE_SOURCE_TYPE = "ONLINE_CARE_QUESTION_BANK_V6"


DIFFICULTY_LABELS = {
    1: "容易",
    2: "中等",
    3: "难题",
}

PRIVACY_LEVELS = {
    "低隐私": 1,
    "中隐私": 2,
    "高隐私": 3,
}

PRIVACY_LABELS = {
    1: "低隐私",
    2: "中隐私",
    3: "高隐私",
}

SAFETY_LEVELS = {
    "常规关怀": 1,
    "重点关注": 2,
    "紧急响应": 3,
}

SAFETY_ACTIONS = {
    "急救": "停止普通关怀，建议立即联系120或所在地急救服务，并确认身边是否有人。",
    "自伤": "保持陪伴，立即连接专业或急救支持，不承诺保密，不说教或转移话题。",
    "人身安全": "先确认当前安全；存在即时危险时建议联系110或所在地紧急服务。",
    "紧急联系人": "确认一位当前可联系的人，不索取无关的身份、账户或证件信息。",
}


def infer_response_mode(question_text):
    if "满分10分" in question_text:
        return "0—10分"
    if re.search(r"几点|什么时间|哪些时间", question_text):
        return "时间"
    if re.search(r"多久|几次|每天|一周|多少支|多少水|大概多少", question_text):
        return "频率或数量"
    if re.search(r"哪类|哪些|哪种|哪个|什么方式|还是", question_text):
        return "选项引导"
    if re.search(r"有没有|会不会|是否", question_text):
        return "是／否后追问"
    return "开放回答"


def escape_json_for_html(value):
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def normalize_health_questions(questions):
    rows = []
    for item in questions:
        row = dict(item)
        row["kind"] = "quiz"
        row["display_id"] = f"#{item['id']}"
        row["stage"] = ""
        row["privacy"] = ""
        row["section_level"] = item["difficulty_level"]
        rows.append(row)
    return rows


def parse_care_questions(path):
    rows = []
    category = None
    item_pattern = re.compile(r"^\d+\.\s*(.*?)`([^`]+)`\s*$")
    heading_pattern = re.compile(r"^##\s+(.+)$")

    for line in path.read_text(encoding="utf-8").splitlines():
        heading = heading_pattern.match(line)
        if heading:
            category = heading.group(1).strip()
            continue

        match = item_pattern.match(line)
        if not match or not category:
            continue

        question_text = match.group(1).strip()
        tags = [part.strip() for part in re.split(r"[｜|]", match.group(2)) if part.strip()]
        stage = tags[0] if tags else "未标记"
        privacy = tags[1] if len(tags) > 1 else "中隐私"
        safety = tags[2] if len(tags) > 2 else "常规关怀"
        safety_route = tags[3] if len(tags) > 3 else ""
        level = PRIVACY_LEVELS.get(privacy, 2)
        section_level = level
        idx = len(rows) + 1
        fingerprint = hashlib.md5(
            f"online_care|{category}|{question_text}|{stage}|{privacy}".encode("utf-8")
        ).hexdigest()
        rows.append(
            {
                "id": idx,
                "display_id": f"#{idx}",
                "kind": "care",
                "status": "ENABLED",
                "category": category,
                "tags_json": tags,
                "stage": stage,
                "privacy": privacy,
                "safety": safety,
                "safety_route": safety_route,
                "safety_action": SAFETY_ACTIONS.get(safety_route, ""),
                "response_mode": infer_response_mode(question_text),
                "question_text": question_text,
                "difficulty_level": level,
                "section_level": section_level,
                "difficulty": "NORMAL",
                "risk_level": SAFETY_LEVELS.get(safety, 1),
                "explanation": "",
                "source_text": str(path),
                "source_type": CARE_SOURCE_TYPE,
                "reference_source": str(path),
                "options_json": [],
                "correct_option": "",
                "semantic_fingerprint": fingerprint,
            }
        )
    return rows


def build_datasets():
    health_questions = normalize_health_questions(json.loads(HEALTH_INPUT.read_text(encoding="utf-8")))
    care_questions = parse_care_questions(CARE_INPUT)
    return [
        {
            "id": "health",
            "title": "健康知识题库",
            "shortTitle": "健康知识",
            "kind": "quiz",
            "unit": "题",
            "levelMode": "难度",
            "levels": {str(key): label for key, label in DIFFICULTY_LABELS.items()},
            "sectionLevels": {str(key): label for key, label in DIFFICULTY_LABELS.items()},
            "levelOrder": [3, 2, 1],
            "metricOrder": [1, 2, 3],
            "summary": "显示题目、选项、答案和解析",
            "questions": health_questions,
        },
        {
            "id": "care",
            "title": "线上关怀问题库",
            "shortTitle": "关怀问题",
            "kind": "care",
            "unit": "问",
            "levelMode": "隐私级别",
            "levels": {str(key): label for key, label in PRIVACY_LABELS.items()},
            "sectionLevels": {"1": "低隐私", "2": "中隐私", "3": "高隐私"},
            "levelOrder": [1, 2, 3],
            "metricOrder": [1, 2, 3],
            "summary": "显示聊天问题、使用阶段、隐私级别和安全响应路径",
            "questions": care_questions,
        },
    ]


def validate_datasets(datasets):
    for dataset in datasets:
        questions = dataset["questions"]
        if not questions:
            raise SystemExit(f"{dataset['id']} has no questions")
        id_counts = Counter(item["id"] for item in questions)
        if any(count > 1 for count in id_counts.values()):
            raise SystemExit(f"{dataset['id']} has duplicate ids")
        text_counts = Counter(item["question_text"] for item in questions)
        duplicates = [text for text, count in text_counts.items() if count > 1]
        if duplicates:
            raise SystemExit(f"{dataset['id']} has duplicate question_text: {duplicates[:5]}")
        fp_counts = Counter(item["semantic_fingerprint"] for item in questions)
        if any(count > 1 for count in fp_counts.values()):
            raise SystemExit(f"{dataset['id']} has duplicate semantic_fingerprint")
        if dataset["kind"] == "quiz":
            for item in questions:
                option_texts = [option["text"] for option in item["options_json"]]
                if len(option_texts) != 4 or len(set(option_texts)) != 4:
                    raise SystemExit(f"Question {item['id']} has invalid options")
        else:
            for item in questions:
                if item["stage"] not in {"初次了解", "熟悉后", "必要时"}:
                    raise SystemExit(f"Care question {item['id']} has invalid stage")
                if item["privacy"] not in PRIVACY_LEVELS:
                    raise SystemExit(f"Care question {item['id']} has invalid privacy")
                if item["safety"] not in SAFETY_LEVELS:
                    raise SystemExit(f"Care question {item['id']} has invalid safety level")
                if item["question_text"].count("？") + item["question_text"].count("?") != 1:
                    raise SystemExit(f"Care question {item['id']} must contain one main question")
                if item["safety"] == "紧急响应" and not item["safety_action"]:
                    raise SystemExit(f"Care question {item['id']} has no emergency action")


def tab_buttons(datasets):
    buttons = []
    for index, dataset in enumerate(datasets):
        active = index == 0
        buttons.append(
            '<button class="tab" type="button" role="tab" '
            f'data-bank="{html.escape(dataset["id"])}" '
            f'aria-selected="{str(active).lower()}">'
            f'<span class="tab-title">{html.escape(dataset["shortTitle"])}</span>'
            f'<span class="tab-count">{len(dataset["questions"])} {html.escape(dataset["unit"])}</span>'
            "</button>"
        )
    return "\n        ".join(buttons)


def build_html(datasets):
    data = escape_json_for_html(datasets)
    tabs = tab_buttons(datasets)
    template = Template(
        """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>题库审题台</title>
  <style>
    :root {
      --paper: #f6f3ea;
      --panel: #fffdf7;
      --ink: #1d2a2a;
      --muted: #687271;
      --line: #d9d2c3;
      --teal: #0f6f68;
      --teal-dark: #094b47;
      --rust: #b95633;
      --amber: #d8a03d;
      --green-soft: #e4f0e7;
      --amber-soft: #f7ecd2;
      --rust-soft: #f5dfd6;
      --shadow: 0 10px 30px rgba(46, 39, 25, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background:
        linear-gradient(90deg, rgba(29, 42, 42, 0.035) 1px, transparent 1px),
        linear-gradient(180deg, rgba(29, 42, 42, 0.035) 1px, transparent 1px),
        var(--paper);
      background-size: 28px 28px;
      color: var(--ink);
      font-family: "Avenir Next", "Hiragino Sans GB", "PingFang SC", "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }

    button,
    input,
    select {
      font: inherit;
    }

    .shell {
      width: min(1480px, calc(100% - 32px));
      margin: 0 auto;
      padding: 20px 0 48px;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 10;
      margin: 0;
      padding: 14px 16px;
      border-bottom: 1px solid rgba(29, 42, 42, 0.12);
      background: rgba(246, 243, 234, 0.92);
      backdrop-filter: blur(16px);
    }

    .topbar-inner {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 16px;
      align-items: end;
      width: min(1480px, 100%);
      margin: 0 auto;
    }

    h1 {
      margin: 0;
      font-family: "Iowan Old Style", "Songti SC", "STSong", serif;
      font-size: 30px;
      line-height: 1.12;
      font-weight: 700;
    }

    .meta-line {
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(84px, 1fr));
      gap: 8px;
      min-width: 430px;
    }

    .metric {
      border: 1px solid var(--line);
      background: rgba(255, 253, 247, 0.82);
      padding: 10px 12px;
      min-height: 62px;
    }

    .metric .value {
      display: block;
      font-size: 22px;
      line-height: 1;
      font-weight: 800;
    }

    .metric .label {
      display: block;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }

    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 253, 247, 0.72);
    }

    .tab {
      min-height: 42px;
      border: 0;
      border-radius: 6px;
      padding: 7px 14px;
      color: var(--muted);
      background: transparent;
      cursor: pointer;
      display: inline-flex;
      align-items: baseline;
      gap: 8px;
    }

    .tab[aria-selected="true"] {
      color: #fff;
      background: var(--teal-dark);
      box-shadow: 0 7px 14px rgba(9, 75, 71, 0.18);
    }

    .tab-title {
      font-weight: 800;
    }

    .tab-count {
      font-size: 12px;
      opacity: 0.8;
    }

    .controls {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) 210px auto;
      gap: 10px;
      align-items: center;
      margin: 0 0 20px;
    }

    .search,
    .select {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 12px;
      outline: none;
      box-shadow: inset 0 0 0 1px transparent;
    }

    .search:focus,
    .select:focus {
      border-color: var(--teal);
      box-shadow: inset 0 0 0 1px var(--teal);
    }

    .segments {
      display: flex;
      gap: 6px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 253, 247, 0.72);
    }

    .segment {
      min-height: 34px;
      border: 0;
      border-radius: 4px;
      padding: 0 12px;
      color: var(--muted);
      background: transparent;
      cursor: pointer;
      white-space: nowrap;
    }

    .segment[aria-pressed="true"] {
      color: #fff;
      background: var(--teal-dark);
      box-shadow: 0 5px 12px rgba(9, 75, 71, 0.2);
    }

    .section {
      margin-top: 22px;
      border-top: 3px solid var(--ink);
      padding-top: 14px;
    }

    .section-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }

    .section-title {
      margin: 0;
      font-family: "Iowan Old Style", "Songti SC", "STSong", serif;
      font-size: 22px;
      line-height: 1.2;
    }

    .section-count {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
    }

    .question {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .question-top {
      display: grid;
      grid-template-columns: 58px 1fr auto;
      gap: 12px;
      align-items: start;
      padding: 14px 14px 10px;
      border-bottom: 1px solid rgba(217, 210, 195, 0.8);
      background: linear-gradient(180deg, rgba(255, 253, 247, 0.95), rgba(249, 244, 233, 0.78));
    }

    .qid {
      display: inline-grid;
      place-items: center;
      min-width: 44px;
      height: 36px;
      border: 1px solid rgba(29, 42, 42, 0.22);
      border-radius: 6px;
      color: var(--teal-dark);
      font-weight: 800;
      font-size: 14px;
      background: #f7f1df;
    }

    .question-title {
      margin: 0;
      font-size: 16px;
      line-height: 1.55;
      font-weight: 750;
    }

    .chips {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
      max-width: 270px;
    }

    .chip {
      min-height: 24px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0 8px;
      font-size: 12px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.55);
      white-space: nowrap;
    }

    .chip.diff-1 {
      color: #2d6840;
      border-color: #b8d6bc;
      background: var(--green-soft);
    }

    .chip.diff-2 {
      color: #7d5d10;
      border-color: #e4c675;
      background: var(--amber-soft);
    }

    .chip.diff-3 {
      color: #8a381f;
      border-color: #e3b09e;
      background: var(--rust-soft);
    }

    .options {
      display: grid;
      gap: 7px;
      padding: 12px 14px;
      margin: 0;
      list-style: none;
    }

    .option {
      display: grid;
      grid-template-columns: 30px 1fr;
      gap: 8px;
      align-items: start;
      min-height: 38px;
      border: 1px solid rgba(217, 210, 195, 0.9);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fffdfa;
    }

    .option-key {
      display: inline-grid;
      place-items: center;
      width: 24px;
      height: 24px;
      border-radius: 4px;
      background: #eee8da;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }

    .option-text {
      font-size: 14px;
      line-height: 1.5;
    }

    .option.correct {
      border-color: rgba(15, 111, 104, 0.5);
      background: linear-gradient(90deg, rgba(15, 111, 104, 0.12), rgba(255, 253, 247, 0.95));
    }

    .option.correct .option-key {
      background: var(--teal-dark);
      color: #fff;
    }

    .answer {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      padding: 0 14px 12px;
      color: var(--teal-dark);
      font-size: 14px;
      line-height: 1.5;
      font-weight: 700;
    }

    .answer-label {
      min-width: 64px;
      color: var(--muted);
      font-weight: 600;
    }

    .explanation {
      border-top: 1px solid rgba(217, 210, 195, 0.8);
      padding: 12px 14px 14px;
      background: #faf6ea;
      color: #3f4847;
      font-size: 14px;
      line-height: 1.65;
    }

    .care-detail {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 14px 14px;
      background: #faf6ea;
      color: #3f4847;
      font-size: 13px;
      line-height: 1.5;
    }

    .care-detail span {
      border: 1px solid rgba(217, 210, 195, 0.9);
      border-radius: 999px;
      padding: 5px 10px;
      background: rgba(255, 253, 247, 0.8);
    }

    .care-action {
      flex: 1 0 100%;
      border-left: 3px solid var(--rust);
      border-radius: 4px;
      padding: 9px 11px;
      background: var(--rust-soft);
      color: #6f2e1d;
      font-size: 14px;
      line-height: 1.6;
    }

    .empty {
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: rgba(255, 253, 247, 0.7);
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }

    @media (max-width: 980px) {
      .topbar-inner,
      .controls {
        grid-template-columns: 1fr;
      }

      .metrics {
        min-width: 0;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 640px) {
      .shell {
        width: min(100% - 20px, 1480px);
        padding-top: 10px;
      }

      .topbar {
        padding: 12px 10px;
      }

      h1 {
        font-size: 24px;
      }

      .tabs,
      .segments {
        overflow-x: auto;
        flex-wrap: nowrap;
      }

      .question-top {
        grid-template-columns: 48px 1fr;
      }

      .chips {
        grid-column: 1 / -1;
        justify-content: flex-start;
        max-width: none;
      }
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <div>
        <h1 id="pageTitle">题库审题台</h1>
        <div class="meta-line" id="pageMeta"></div>
      </div>
      <div class="metrics" aria-label="题库统计">
        <div class="metric"><span class="value" id="metricTotal">0</span><span class="label" id="metricTotalLabel">全部</span></div>
        <div class="metric"><span class="value" id="metricOne">0</span><span class="label" id="metricOneLabel"></span></div>
        <div class="metric"><span class="value" id="metricTwo">0</span><span class="label" id="metricTwoLabel"></span></div>
        <div class="metric"><span class="value" id="metricThree">0</span><span class="label" id="metricThreeLabel"></span></div>
      </div>
    </div>
  </div>

  <main class="shell">
    <nav class="tabs" role="tablist" aria-label="题库切换">
        $tabs
    </nav>

    <section class="controls" aria-label="筛选">
      <input class="search" id="search" type="search" placeholder="搜索题干、选项、解析、标签">
      <select class="select" id="category"></select>
      <div class="segments" role="group" id="levelSegments" aria-label="分组筛选">
        <button class="segment" type="button" data-level="all" aria-pressed="true">全部</button>
        <button class="segment" type="button" data-level="1" aria-pressed="false"></button>
        <button class="segment" type="button" data-level="2" aria-pressed="false"></button>
        <button class="segment" type="button" data-level="3" aria-pressed="false"></button>
      </div>
    </section>

    <div id="resultMeta" class="meta-line"></div>
    <div id="content"></div>
  </main>

  <script id="question-banks" type="application/json">$data</script>
  <script>
    const banks = JSON.parse(document.getElementById("question-banks").textContent);
    const bankById = Object.fromEntries(banks.map(function(bank) { return [bank.id, bank]; }));
    const pageTitle = document.getElementById("pageTitle");
    const pageMeta = document.getElementById("pageMeta");
    const content = document.getElementById("content");
    const resultMeta = document.getElementById("resultMeta");
    const searchInput = document.getElementById("search");
    const categorySelect = document.getElementById("category");
    const tabButtons = Array.from(document.querySelectorAll(".tab"));
    const segmentButtons = Array.from(document.querySelectorAll(".segment"));
    const metricIds = [
      ["metricOne", "metricOneLabel"],
      ["metricTwo", "metricTwoLabel"],
      ["metricThree", "metricThreeLabel"]
    ];
    let activeBank = banks[0];
    let activeLevel = "all";

    function unitText(count) {
      return count + " " + activeBank.unit;
    }

    function countByLevel(questions) {
      return questions.reduce(function(result, item) {
        const key = String(item.difficulty_level);
        result[key] = (result[key] || 0) + 1;
        return result;
      }, {});
    }

    function updateHeader() {
      const counts = countByLevel(activeBank.questions);
      pageTitle.textContent = activeBank.title;
      pageMeta.textContent = "当前题库：" + unitText(activeBank.questions.length) + " · " + activeBank.levelMode + "分组 · " + activeBank.summary;
      document.getElementById("metricTotal").textContent = activeBank.questions.length;
      document.getElementById("metricTotalLabel").textContent = "全部" + activeBank.unit;
      activeBank.metricOrder.forEach(function(level, index) {
        const valueId = metricIds[index][0];
        const labelId = metricIds[index][1];
        document.getElementById(valueId).textContent = counts[String(level)] || 0;
        document.getElementById(labelId).textContent = activeBank.levels[String(level)];
      });
    }

    function updateTabs() {
      tabButtons.forEach(function(button) {
        button.setAttribute("aria-selected", String(button.dataset.bank === activeBank.id));
      });
    }

    function updateCategoryOptions() {
      const counts = activeBank.questions.reduce(function(result, item) {
        result[item.category] = (result[item.category] || 0) + 1;
        return result;
      }, {});
      const categories = Object.keys(counts).sort(function(a, b) { return a.localeCompare(b, "zh-CN"); });
      categorySelect.textContent = "";
      const allOption = document.createElement("option");
      allOption.value = "";
      allOption.textContent = "全部分类 (" + activeBank.questions.length + ")";
      categorySelect.appendChild(allOption);
      categories.forEach(function(category) {
        const option = document.createElement("option");
        option.value = category;
        option.textContent = category + " (" + counts[category] + ")";
        categorySelect.appendChild(option);
      });
    }

    function updateSegments() {
      segmentButtons.forEach(function(button) {
        const level = button.dataset.level;
        button.textContent = level === "all" ? "全部" : activeBank.levels[level];
        button.setAttribute("aria-pressed", String(level === activeLevel));
      });
    }

    function textForSearch(item) {
      return [
        item.question_text,
        item.category,
        item.explanation,
        item.correct_option,
        item.reference_source,
        item.stage,
        item.privacy,
        item.safety,
        item.safety_route,
        item.safety_action,
        item.response_mode,
        ...(item.tags_json || []),
        ...(item.options_json || []).map(function(option) { return option.text; })
      ].join(" ").toLowerCase();
    }

    function optionMarkup(item) {
      return item.options_json.map(function(option) {
        const isCorrect = option.key === item.correct_option;
        return [
          '<li class="option ', isCorrect ? "correct" : "", '">',
          '<span class="option-key">', escapeHtml(option.key), '</span>',
          '<span class="option-text">', escapeHtml(option.text), '</span>',
          '</li>'
        ].join("");
      }).join("");
    }

    function answerText(item) {
      const answer = item.options_json.find(function(option) { return option.key === item.correct_option; });
      return answer ? item.correct_option + ". " + answer.text : item.correct_option;
    }

    function quizCard(item) {
      return [
        '<article class="question">',
        '<div class="question-top">',
        '<span class="qid">', escapeHtml(item.display_id), '</span>',
        '<h3 class="question-title">', escapeHtml(item.question_text), '</h3>',
        chipMarkup(item),
        '</div>',
        '<ul class="options">', optionMarkup(item), '</ul>',
        '<div class="answer"><span class="answer-label">正确答案</span><span>', escapeHtml(answerText(item)), '</span></div>',
        '<div class="explanation">', escapeHtml(item.explanation), '</div>',
        '</article>'
      ].join("");
    }

    function careCard(item) {
      return [
        '<article class="question">',
        '<div class="question-top">',
        '<span class="qid">', escapeHtml(item.display_id), '</span>',
        '<h3 class="question-title">', escapeHtml(item.question_text), '</h3>',
        chipMarkup(item),
        '</div>',
        '<div class="care-detail">',
        '<span>使用阶段：', escapeHtml(item.stage), '</span>',
        '<span>隐私级别：', escapeHtml(item.privacy), '</span>',
        '<span>回答方式：', escapeHtml(item.response_mode), '</span>',
        '<span>关注等级：', escapeHtml(item.safety), '</span>',
        item.safety_route ? '<span>响应路径：' + escapeHtml(item.safety_route) + '</span>' : '',
        '<span>分类：', escapeHtml(item.category), '</span>',
        item.safety_action ? '<div class="care-action"><strong>响应动作：</strong>' + escapeHtml(item.safety_action) + '</div>' : '',
        '</div>',
        '</article>'
      ].join("");
    }

    function chipMarkup(item) {
      const chips = [];
      chips.push('<span class="chip diff-' + item.difficulty_level + '">' + escapeHtml(activeBank.levels[String(item.difficulty_level)]) + '</span>');
      if (item.kind === "care") {
        chips.push('<span class="chip">' + escapeHtml(item.stage) + '</span>');
        if (item.safety !== "常规关怀") {
          chips.push('<span class="chip">' + escapeHtml(item.safety) + '</span>');
        }
        chips.push('<span class="chip">' + escapeHtml(item.category) + '</span>');
      } else {
        chips.push('<span class="chip">' + escapeHtml(item.category) + '</span>');
        (item.tags_json || []).slice(0, 2).forEach(function(tag) {
          chips.push('<span class="chip">' + escapeHtml(tag) + '</span>');
        });
      }
      return '<div class="chips">' + chips.join("") + '</div>';
    }

    function questionCard(item) {
      return activeBank.kind === "care" ? careCard(item) : quizCard(item);
    }

    function sectionMarkup(level, items) {
      if (!items.length) return "";
      const sectionLabels = activeBank.sectionLevels || activeBank.levels;
      return [
        '<section class="section">',
        '<div class="section-head">',
        '<h2 class="section-title">', escapeHtml(sectionLabels[String(level)]), '</h2>',
        '<span class="section-count">', items.length, " ", escapeHtml(activeBank.unit), '</span>',
        '</div>',
        '<div class="grid">', items.map(questionCard).join(""), '</div>',
        '</section>'
      ].join("");
    }

    function render() {
      const query = searchInput.value.trim().toLowerCase();
      const category = categorySelect.value;
      const filtered = activeBank.questions.filter(function(item) {
        if (activeLevel !== "all" && String(item.difficulty_level) !== activeLevel) return false;
        if (category && item.category !== category) return false;
        if (query && !textForSearch(item).includes(query)) return false;
        return true;
      });

      resultMeta.textContent = "当前显示 " + filtered.length + " / " + activeBank.questions.length + " " + activeBank.unit;
      if (!filtered.length) {
        content.innerHTML = '<div class="empty">没有匹配的内容</div>';
        return;
      }

      content.innerHTML = activeBank.levelOrder
        .map(function(level) {
          return sectionMarkup(level, filtered.filter(function(item) { return (item.section_level || item.difficulty_level) === level; }));
        })
        .join("");
    }

    function setActiveBank(bankId) {
      activeBank = bankById[bankId] || banks[0];
      activeLevel = "all";
      categorySelect.value = "";
      updateTabs();
      updateHeader();
      updateCategoryOptions();
      updateSegments();
      render();
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    tabButtons.forEach(function(button) {
      button.addEventListener("click", function() {
        setActiveBank(button.dataset.bank);
      });
    });

    segmentButtons.forEach(function(button) {
      button.addEventListener("click", function() {
        activeLevel = button.dataset.level;
        updateSegments();
        render();
      });
    });

    searchInput.addEventListener("input", render);
    categorySelect.addEventListener("change", render);
    setActiveBank(activeBank.id);
  </script>
</body>
</html>
"""
    )
    return template.substitute(data=data, tabs=tabs)


def main():
    datasets = build_datasets()
    validate_datasets(datasets)
    rendered = build_html(datasets)
    for output in OUTPUTS:
        output.write_text(rendered, encoding="utf-8")
    total = sum(len(dataset["questions"]) for dataset in datasets)
    names = ", ".join(str(output) for output in OUTPUTS)
    print(f"Wrote {names} with {total} items across {len(datasets)} tabs")


if __name__ == "__main__":
    main()
