import csv
import json
import os
import re
from glob import glob



mineruparsed='/Users/l/klee_code/git_repos/parse_evaluation/eaa0dd7f-206c-485e-82db-2b4b355ff0a9_origin copy (dragged).pdf-aafdc8db-4703-4b3b-809a-eadc8088d856/full.md'
questionspan_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/question_spans.csv'
output_csv_columns = ['spans', 'original_page_screenshot_paths']
original_page_screenshot_path_root = '/Users/l/klee_code/git_repos/parse_evaluation/splited'
# example:
sample_questions_that_should_be_in_the_same_span_because_they_refer_to_the_same_passage = """
Use the following passage to answer questions 1 and 2.

Of the numerous American automotive pioneers, perhaps among the best known are Charles and Frank Duryea. Beginning their work of automobile building in Springfield,
5 Massachusetts, and, after much rebuilding, they constructed their first successful vehicle in 1892 and 1893. No sooner was this finished than Frank, working alone, began work on a second vehicle having a two-cylinder engine. With this
10 automobile, sufficient capital was attracted in 1895 to form the Duryea Motor Wagon Company in which both brothers were among the stockholders and directors. A short time after the formation of the company, this second
15 automobile was entered by the company in the Chicago Times-Herald automobile race on Thanksgiving Day, November 28, 1895, where Frank Duryea won a victory over the other five contestants—two electric automobiles and
20 three Benz machines imported from Germany.

Source: Excerpt from The 1893 Duryea Automobile by Don H. Berkebile.

Which of the following is the best summary of the passage?
a. There were many automotive pioneers in America, but the best known were the brothers Charles and Frank Duryea, who began building automobiles in Springfield, Massachusetts. b. Charles and Frank Duryea were among the best-known American automotive pioneers, but Frank was more famous than his brother Charles because Frank won the Chicago Times-Herald automobile race.
c. On Thanksgiving Day, November 28, 1895, Frank Duryea won the Chicago Times-Herald automobile race over five other contestants: two electric automobiles and three Benz machines from Germany.
d. Charles and Frank Duryea were pioneering automobile builders, and Frank developed a profitable two-cylinder engine vehicle with which he won the Chicago Times-Herald automobile race.
e. Although Frank Duryea developed a two-cylinder engine vehicle, both he and his brother Charles profited from it because it earned them the capital to start the Duryea Motor Wagon Company.

In the passage, the author describes the kinds of cars Frank Duryea defeated in the Chicago Times-Herald automobile race in order to
a. show that the best automobiles in the world are built in Springfield, Massachusetts.
b. imply that he would later develop an electric car for the Duryea Motor Wagon Company.
c. indicate that the quality of automobiles being developed in Europe was very poor at the time.
d. suggest that the kind of car he drove is what helped him win the race.
e. help the reader understand the differences between two-cylinder vehicles and electric automobiles.
"""
# split the mineruparsed data into csvs and save it into output_csv

SPAN_TRIGGER_RE = re.compile(r'^\s*Use the following passage', re.IGNORECASE)
# text_level=1 items that should stay inside a span (passage/source sub-labels)
IN_SPAN_TOP_LEVEL_RE = re.compile(r'^\s*(Passage|Source)\s+\d+\s*$', re.IGNORECASE)


def _is_section_break(item):
    if item.get('type') != 'text':
        return False
    if item.get('text_level') != 1:
        return False
    text = (item.get('text') or '').strip()
    return bool(text) and not IN_SPAN_TOP_LEVEL_RE.match(text)


def _find_content_list(root_dir):
    candidates = glob(os.path.join(root_dir, '*_content_list.json'))
    # prefer the non-v2 file (matches the original full.md layout)
    primary = [p for p in candidates if not p.endswith('_v2.json')]
    chosen = primary[0] if primary else candidates[0]
    with open(chosen) as f:
        return json.load(f)


def _page_idx_to_pdf_path(page_idx):
    # splited PDFs are 1-indexed: page_idx 0 -> _p01.pdf
    filename = f'praxis_core_pp copy 2_p{page_idx + 1:02d}.pdf'
    return os.path.join(original_page_screenshot_path_root, filename)


def _render_item(item):
    t = item.get('type')
    if t == 'page_number':
        return ''
    if t == 'header':
        # running page header — strip; it repeats on every page
        return ''
    if t == 'text':
        text = (item.get('text') or '').strip()
        if not text:
            return ''
        level = item.get('text_level')
        if level:
            return f'{"#" * level} {text}'
        return text
    if t == 'list':
        items = item.get('list_items') or []
        return '\n'.join(s.strip() for s in items if s and s.strip())
    if t == 'equation':
        return (item.get('text') or '').strip()
    if t == 'table':
        parts = []
        for cap in item.get('table_caption') or []:
            cap = cap.strip()
            if cap:
                parts.append(cap)
        body = (item.get('table_body') or '').strip()
        if body:
            parts.append(body)
        for fn in item.get('table_footnote') or []:
            fn = fn.strip()
            if fn:
                parts.append(fn)
        return '\n'.join(parts)
    if t in ('image', 'chart'):
        img = item.get('img_path') or ''
        caption_key = 'image_caption' if t == 'image' else 'chart_caption'
        footnote_key = 'image_footnote' if t == 'image' else 'chart_footnote'
        parts = []
        for cap in item.get(caption_key) or []:
            cap = cap.strip()
            if cap:
                parts.append(cap)
        if img:
            parts.append(f'![]({img})')
        content = (item.get('content') or '').strip()
        if content:
            parts.append(content)
        for fn in item.get(footnote_key) or []:
            fn = fn.strip()
            if fn:
                parts.append(fn)
        return '\n'.join(parts)
    return ''


def _split_into_spans(items):
    spans = []
    current_items = None
    for item in items:
        if item.get('type') == 'text' and SPAN_TRIGGER_RE.match(item.get('text') or ''):
            if current_items:
                spans.append(current_items)
            current_items = [item]
        elif current_items is not None:
            if _is_section_break(item):
                spans.append(current_items)
                current_items = None
            else:
                current_items.append(item)
    if current_items:
        spans.append(current_items)
    return spans


def _serialize_span(span_items):
    rendered = []
    pages_seen = []
    seen = set()
    for item in span_items:
        page_idx = item.get('page_idx')
        if page_idx is not None and page_idx not in seen:
            seen.add(page_idx)
            pages_seen.append(page_idx)
        chunk = _render_item(item)
        if chunk:
            rendered.append(chunk)
    text = '\n\n'.join(rendered).strip()
    pdf_paths = [_page_idx_to_pdf_path(p) for p in sorted(pages_seen)]
    return text, pdf_paths


def main():
    root_dir = os.path.dirname(mineruparsed)
    items = _find_content_list(root_dir)
    spans = _split_into_spans(items)
    out_dir = os.path.dirname(questionspan_output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(questionspan_output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(output_csv_columns)
        for span_items in spans:
            text, pdf_paths = _serialize_span(span_items)
            if not text:
                continue
            writer.writerow([text, json.dumps(pdf_paths)])
    print(f'wrote {len(spans)} spans to {questionspan_output_csv}')



if __name__ == '__main__':
    main()
