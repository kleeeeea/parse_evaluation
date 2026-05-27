import csv
import os
import re

questionspan_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/question_spans.csv'
individual_question_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/individual_questions.csv'
individual_question_output_columns = [
    'question_number',
    'passage',
    'question',
    'original_page_screenshot_paths',
]

# Each row in question_spans.csv groups a passage with the questions that refer to it.
# Here we split each span into one row per question, keeping the shared passage
# alongside every question for downstream evaluation.

# A question header looks like a line starting with "<number>. " — e.g. "1. Which ...".
# - Optional leading horizontal whitespace covers mineru's occasional indentation.
# - The lookahead for \s (not [ \t]+) lets a stem that wraps to the next line still
#   anchor on the digit-period.
# - Choice labels ("a.", "b.", ...) don't start with digits so they are excluded.
# - In-passage line numbers ("5 Massachusetts") have no trailing period so they
#   are excluded too.
QUESTION_HEADER_RE = re.compile(r'^[ \t]*(\d+)\.(?=\s)', re.MULTILINE)


def _split_span_into_questions(span_text):
    """Return (passage_text, [(question_number, question_text), ...])."""
    matches = list(QUESTION_HEADER_RE.finditer(span_text))
    if not matches:
        return span_text.strip(), []
    passage = span_text[:matches[0].start()].rstrip()
    questions = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(span_text)
        chunk = span_text[start:end].strip()
        questions.append((int(m.group(1)), chunk))
    return passage, questions


def split_consecutive_problem_spans_into_individual_questions(current_questionspan_csv):
    out_dir = os.path.dirname(individual_question_output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    rows_in = 0
    rows_out = 0
    with open(current_questionspan_csv, newline='') as f_in, \
            open(individual_question_output_csv, 'w', newline='') as f_out:
        reader = csv.DictReader(f_in)
        writer = csv.DictWriter(f_out, fieldnames=individual_question_output_columns)
        writer.writeheader()
        for row in reader:
            rows_in += 1
            span_text = row.get('spans') or ''
            page_paths = row.get('original_page_screenshot_paths') or '[]'
            passage, questions = _split_span_into_questions(span_text)
            if not questions:
                # Span had no parseable questions; skip rather than emit empty rows.
                continue
            for qnum, qtext in questions:
                writer.writerow({
                    'question_number': qnum,
                    'passage': passage,
                    'question': qtext,
                    'original_page_screenshot_paths': page_paths,
                })
                rows_out += 1
    print(f'read {rows_in} spans, wrote {rows_out} questions to {individual_question_output_csv}')


if __name__ == '__main__':
    split_consecutive_problem_spans_into_individual_questions(questionspan_output_csv)
