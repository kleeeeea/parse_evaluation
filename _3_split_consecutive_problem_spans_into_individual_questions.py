import csv
import os
from dataclasses import asdict

from dataclass_ import IndividualQuestionRow, columns
from exam_formats import PRAXIS_READING, ExamFormat, question_number_match
from stage import Stage
from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from _2_split_question_main_body_into_consecutive_problem_spans import SplitQuestionMainbodyIntoSpansStage
from tests.fixture._constants import mineruparsed

individual_question_output_csv_basename = 'individual_questions.csv'

individual_question_output_columns = columns(IndividualQuestionRow)

# Each row in question_spans.csv groups a passage with the questions that refer to it.
# Here we split each span into one row per question, keeping the shared passage
# alongside every question for downstream evaluation.


def _split_span_into_questions(span_text, exam_format: ExamFormat, next_question_number: int):
    """Return (passage_text, [(question_number, question_text), ...], next_question_number).

    一行只有在「匹配 question_line_re 且题号 == next_question_number（全局
    连续计数）」时才算题目起始——span 内的编号列表（plt Case History 3 的
    Goals 1.–4.、Q17 题干里的子问题 1.–3.）题号对不上，留在 passage/题干里。
    """
    passage_lines = []
    questions = []  # [(qnum, [lines])]
    for line in span_text.splitlines():
        if question_number_match(exam_format, line) == next_question_number:
            questions.append((next_question_number, [line]))
            next_question_number += 1
        elif questions:
            questions[-1][1].append(line)
        else:
            passage_lines.append(line)
    return (
        '\n'.join(passage_lines).rstrip(),
        [(qnum, '\n'.join(lines).strip()) for qnum, lines in questions],
        next_question_number,
    )


class SplitSpansIntoIndividualQuestionsStage(Stage):
    # …/{dataset}/outputs/question_spans.csv -> …/{dataset}/outputs/individual_questions.csv
    output_basename = individual_question_output_csv_basename

    def _produce(self, output_path, current_questionspan_csv):
        rows_in = 0
        rows_out = 0
        next_question_number = 1  # 跨 span 的全局连续题号计数
        with open(current_questionspan_csv, newline='') as f_in, \
                open(output_path, 'w', newline='') as f_out:
            reader = csv.DictReader(f_in)
            writer = csv.DictWriter(f_out, fieldnames=individual_question_output_columns)
            writer.writeheader()
            for row in reader:
                rows_in += 1
                span_text = row.get('spans') or ''
                page_paths = row.get('original_page_screenshot_paths') or '[]'
                passage, questions, next_question_number = _split_span_into_questions(
                    span_text, self.exam_format, next_question_number)
                if not questions:
                    # Span had no parseable questions; skip rather than emit empty rows.
                    continue
                for qnum, qtext in questions:
                    writer.writerow(asdict(IndividualQuestionRow(
                        question_number=str(qnum),
                        passage=passage,
                        question=qtext,
                        original_page_screenshot_paths=page_paths,
                    )))
                    rows_out += 1
        print(f'read {rows_in} spans, wrote {rows_out} questions to {output_path}')

if __name__ == '__main__':
    # 从 fixture 的输入 md 沿 _1_ -> _2_ 的 derive 链推出 question_spans.csv
    SplitSpansIntoIndividualQuestionsStage().run(
        SplitQuestionMainbodyIntoSpansStage().derive_output_path(
            GetQuestionsMainbodyStage().derive_output_path(mineruparsed)))
