import csv
import os
from dataclasses import asdict

from dataclass_ import PromptRow, columns
from exam_formats import PRAXIS_READING, ExamFormat

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from _2_split_question_main_body_into_consecutive_problem_spans import (
    SplitQuestionMainbodyIntoSpansStage,
)
from _3_split_consecutive_problem_spans_into_individual_questions import (
    SplitSpansIntoIndividualQuestionsStage,
)
from _4_split_mineru_parsed_md_into_consecutive_answer_spans import (
    SplitMineruParsedMdIntoAnswerSpansStage,
)
from _5_join_problems_and_answers import JoinProblemsAndAnswersStage
from tests.fixture._constants import mineruparsed


def main():
    # 每步返回输出路径并作为下一步的输入；输出已存在时各步自动跳过（幂等）
    run_pipeline(mineruparsed, mineruparsed, PRAXIS_READING)


def run_pipeline(question_input_document: str, answer_input_document: str, exam_format: ExamFormat = PRAXIS_READING) -> None:
    questions_mainbody_md = GetQuestionsMainbodyStage(exam_format=exam_format).run(question_input_document)
    questionspan_csv = SplitQuestionMainbodyIntoSpansStage(exam_format=exam_format).run(questions_mainbody_md)
    individual_question_csv = SplitSpansIntoIndividualQuestionsStage(exam_format=exam_format).run(questionspan_csv)
    answerspan_csv = SplitMineruParsedMdIntoAnswerSpansStage(exam_format=exam_format).run(answer_input_document)
    joined_output_csv = JoinProblemsAndAnswersStage().run(individual_question_csv, answerspan_csv)

    # prompts.csv 与 joined 输出同目录
    prompts_output_csv = os.path.join(os.path.dirname(joined_output_csv), 'prompts.csv')
    # keep the original metadata columns — prompts.csv is a superset of the joined
    # CSV with the derived `id` and `prompt` fields added on top.
    # 行 schema 统一定义在 dataclass_.py，全流水线复用（构造即校验、frozen 不可变）
    prompts_output_columns = columns(PromptRow)

    os.makedirs(os.path.dirname(prompts_output_csv), exist_ok=True)
    _rows_written = 0
    with open(joined_output_csv, newline='') as _f_in, open(prompts_output_csv, 'w', newline='') as _f_out:
        _reader = csv.DictReader(_f_in)
        _writer = csv.DictWriter(_f_out, fieldnames=prompts_output_columns)
        _writer.writeheader()
        for _row in _reader:
            _writer.writerow(asdict(PromptRow(**_row)))
            _rows_written += 1
    print(f'wrote {_rows_written} prompts to {prompts_output_csv}')


if __name__ == '__main__':
    main()
