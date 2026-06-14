import csv
import os
import re
from dataclasses import asdict

from dataclass_ import AnswerSpanRow, columns
from exam_formats import PRAXIS_READING, ExamFormat
from stage import Stage
from tests.fixture._constants import mineruparsed
from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from _2_split_question_main_body_into_consecutive_problem_spans import SplitQuestionMainbodyIntoSpansStage
from _3_split_consecutive_problem_spans_into_individual_questions import SplitSpansIntoIndividualQuestionsStage

answerspan_output_csv_basename = 'answer_spans.csv'
answerspan_output_columns = columns(AnswerSpanRow)

# 一条答案的起始行由 exam_format.answer_header_re 决定：
# praxis: "1. d. Only choice d …"；plt 短答题: "## 1. Sample Response …"。

# Top-level markdown headers — used as section boundaries.
TOP_LEVEL_HEADER_RE = re.compile(r'^#\s+(.*)$')
# Sub-labels that may appear inside an answer section and should NOT end it.
IN_SECTION_TOP_LEVEL_RE = re.compile(r'^\s*(Passage|Source)\s+\d+\s*$', re.IGNORECASE)
# A top-level header that contains this phrase opens the answer section.
ANSWERS_SECTION_MARKER_RE = re.compile(r'Answers and Explanations', re.IGNORECASE)


def _split_markdown_into_answer_spans(md_text, exam_format: ExamFormat = PRAXIS_READING):
    """Walk the markdown line by line.

    Enters "answer mode" at any top-level header (`# …`) whose text contains
    "Answers and Explanations". While in answer mode:
      - a line matching exam_format.answer_header_re starts a new
        numbered-answer span,
      - every subsequent line is appended to the current span,
      - a top-level header that is NOT a Passage/Source sub-label closes the
        current span and exits answer mode (the next test section starts).

    Lines outside answer mode are discarded.
    """
    spans = []
    current = None

    def _flush():
        nonlocal current
        if current is not None:
            spans.append(current)
            current = None

    in_answers = False
    for line in md_text.splitlines():
        header_match = TOP_LEVEL_HEADER_RE.match(line)
        if header_match:
            header_text = header_match.group(1).strip()
            if ANSWERS_SECTION_MARKER_RE.search(header_text):
                # Start of (or re-entry into) an answer section.
                _flush()
                in_answers = True
                continue
            if in_answers and not IN_SECTION_TOP_LEVEL_RE.match(header_text):
                # New top-level section (next test, etc.) — leave answer mode.
                _flush()
                in_answers = False
                continue
            # Otherwise it's a Passage/Source sub-label inside the answers — fall
            # through and let the line be appended to the current answer.
        if not in_answers:
            continue
        m = exam_format.answer_header_re.match(line)
        if m:
            _flush()
            current = {'num': int(m.group(1)), 'lines': [line]}
        elif current is not None:
            current['lines'].append(line)
    _flush()
    return spans


def _serialize_span(span):
    return '\n'.join(span['lines']).strip()


class SplitMineruParsedMdIntoAnswerSpansStage(Stage):
    # …/{mineru任务目录}/full.md -> …/{mineru任务目录}/answer_spans.csv
    output_basename = answerspan_output_csv_basename

    def _produce(self, output_path, current_mineruparsed):
        with open(current_mineruparsed) as f:
            md_text = f.read()
        spans = _split_markdown_into_answer_spans(md_text, self.exam_format)

        # Deduplicate by question_number, keeping the first occurrence.
        seen = set()
        deduped = []
        for s in spans:
            if s['num'] in seen:
                continue
            seen.add(s['num'])
            deduped.append(s)
        deduped.sort(key=lambda s: s['num'])

        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=answerspan_output_columns)
            writer.writeheader()
            for s in deduped:
                writer.writerow(asdict(AnswerSpanRow(
                    question_number=str(s['num']),
                    answer=_serialize_span(s),
                )))

        # Cross-check against the individual questions, if that file exists.
        expected = set()
        # 从输入 md 沿 _1_ -> _2_ -> _3_ 的 derive 链动态推导 individual_questions.csv 的路径
        individual_question_output_csv = SplitSpansIntoIndividualQuestionsStage().derive_output_path(
            SplitQuestionMainbodyIntoSpansStage().derive_output_path(
                GetQuestionsMainbodyStage().derive_output_path(current_mineruparsed)))
        if os.path.exists(individual_question_output_csv):
            with open(individual_question_output_csv) as f:
                for row in csv.DictReader(f):
                    try:
                        expected.add(int(row['question_number']))
                    except (KeyError, TypeError, ValueError):
                        pass
        missing = sorted(expected - seen)
        extra = sorted(seen - expected) if expected else []
        print(f'wrote {len(deduped)} answer spans to {output_path}')
        if missing:
            print(f'  missing answers for questions: {missing}')
        if extra:
            print(f'  extra answers not in individual_questions.csv: {extra}')


if __name__ == '__main__':
    SplitMineruParsedMdIntoAnswerSpansStage().run(mineruparsed)
