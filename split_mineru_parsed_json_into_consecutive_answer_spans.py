import csv
import json
import os
import re
from glob import glob

from git_repos.parse_evaluation.split_consecutive_problem_spans_into_individual_questions import individual_question_output_csv
from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_problem_spans import mineruparsed

answerspan_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/answer_spans.csv'
answerspan_output_columns = ['question_number', 'answer', 'original_page_screenshot_paths']
original_page_screenshot_path_root = '/Users/l/klee_code/git_repos/parse_evaluation/splited'

# A numbered answer line looks like "1. d. Only choice d ..." — i.e. starts with
# "<digits>. " at the start of a string. The same regex matches both standalone
# text items and individual list_items.
ANSWER_HEADER_RE = re.compile(r'^\s*(\d+)\.\s+')

# text_level=1 items that should stay inside the answer section instead of ending it
IN_SECTION_TOP_LEVEL_RE = re.compile(r'^\s*(Passage|Source)\s+\d+\s*$', re.IGNORECASE)
ANSWERS_SECTION_MARKER = 'Answers and Explanations'


def _find_content_list(root_dir):
    candidates = glob(os.path.join(root_dir, '*_content_list.json'))
    # prefer the non-v2 file (matches the original full.md layout)
    primary = [p for p in candidates if not p.endswith('_v2.json')]
    chosen = primary[0] if primary else candidates[0]
    with open(chosen) as f:
        return json.load(f)


def _page_idx_to_pdf_path(page_idx):
    filename = f'praxis_core_pp copy 2_p{page_idx + 1:02d}.pdf'
    return os.path.join(original_page_screenshot_path_root, filename)


def _append_to_current(current, chunk, page_idx):
    if chunk:
        current['parts'].append(chunk)
    if page_idx is not None and page_idx not in current['pages']:
        current['pages'].append(page_idx)


def _split_into_answer_spans(items):
    """Walk content_list items and emit one span per numbered answer.

    Enters "answer mode" at a text_level=1 heading containing
    "Answers and Explanations" and stays there until another top-level heading
    (other than the Passage/Source sub-labels) is encountered. Numbered answers
    can appear either as standalone text items ("1. d. ...") or packed into
    list items (each list_item is itself a numbered answer).
    """
    in_answers = False
    spans = []
    current = None

    def _flush():
        nonlocal current
        if current is not None:
            spans.append(current)
            current = None

    for item in items:
        # Section bookkeeping
        if item.get('type') == 'text' and item.get('text_level') == 1:
            text = (item.get('text') or '').strip()
            if ANSWERS_SECTION_MARKER in text:
                _flush()
                in_answers = True
                continue
            if in_answers and text and not IN_SECTION_TOP_LEVEL_RE.match(text):
                # Hit a different section (e.g. the next test) — leave answer mode.
                _flush()
                in_answers = False
                continue

        if not in_answers:
            continue

        t = item.get('type')
        if t in ('header', 'page_number'):
            continue

        page_idx = item.get('page_idx')

        if t == 'text':
            text = (item.get('text') or '').strip()
            if not text:
                continue
            m = ANSWER_HEADER_RE.match(text)
            if m:
                _flush()
                current = {'num': int(m.group(1)), 'parts': [text], 'pages': [page_idx]}
            elif current is not None:
                _append_to_current(current, text, page_idx)
        elif t == 'list':
            for li in item.get('list_items') or []:
                li = (li or '').strip()
                if not li:
                    continue
                m = ANSWER_HEADER_RE.match(li)
                if m:
                    _flush()
                    current = {'num': int(m.group(1)), 'parts': [li], 'pages': [page_idx]}
                elif current is not None:
                    _append_to_current(current, li, page_idx)
        elif t == 'equation':
            if current is not None:
                _append_to_current(current, (item.get('text') or '').strip(), page_idx)
        elif t == 'table':
            if current is not None:
                body = (item.get('table_body') or '').strip()
                _append_to_current(current, body, page_idx)
        elif t in ('image', 'chart'):
            if current is not None:
                img = item.get('img_path') or ''
                if img:
                    _append_to_current(current, f'![]({img})', page_idx)

    _flush()
    return spans


def _serialize_span(span):
    text = '\n\n'.join(p for p in span['parts'] if p).strip()
    pages = sorted(p for p in span['pages'] if p is not None)
    pdf_paths = [_page_idx_to_pdf_path(p) for p in pages]
    return text, pdf_paths


def split_mineru_parsed_md_into_consecutive_answer_spans(current_mineruparsed):
    root_dir = os.path.dirname(current_mineruparsed)
    items = _find_content_list(root_dir)
    spans = _split_into_answer_spans(items)

    # Deduplicate by question_number, keeping the first occurrence.
    seen = set()
    deduped = []
    for s in spans:
        if s['num'] in seen:
            continue
        seen.add(s['num'])
        deduped.append(s)
    deduped.sort(key=lambda s: s['num'])

    out_dir = os.path.dirname(answerspan_output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(answerspan_output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=answerspan_output_columns)
        writer.writeheader()
        for s in deduped:
            text, pdf_paths = _serialize_span(s)
            writer.writerow({
                'question_number': s['num'],
                'answer': text,
                'original_page_screenshot_paths': json.dumps(pdf_paths),
            })

    # Cross-check against the individual questions, if that file exists.
    expected = set()
    if os.path.exists(individual_question_output_csv):
        with open(individual_question_output_csv) as f:
            for row in csv.DictReader(f):
                try:
                    expected.add(int(row['question_number']))
                except (KeyError, TypeError, ValueError):
                    pass
    missing = sorted(expected - seen)
    extra = sorted(seen - expected) if expected else []
    print(f'wrote {len(deduped)} answer spans to {answerspan_output_csv}')
    if missing:
        print(f'  missing answers for questions: {missing}')
    if extra:
        print(f'  extra answers not in individual_questions.csv: {extra}')


if __name__ == '__main__':
    split_mineru_parsed_md_into_consecutive_answer_spans(mineruparsed)
