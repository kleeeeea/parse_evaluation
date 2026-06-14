from exam_formats import ExamFormat, get_exam_format

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from _2_split_question_main_body_into_consecutive_problem_spans import (
    SplitQuestionMainbodyIntoIndividualQuestionsStage,
)
from _4_split_mineru_parsed_md_into_consecutive_answer_spans import (
    SplitMineruParsedMdIntoAnswerSpansStage,
)
from exam_formats import ExamFormat
from exam_formats import get_exam_format
from parse_evaluation.tests.fixture._constants import plt_8_answer_mineruparsed
from tests.fixture._constants import mineruparsed


def main():
    # 每步返回输出路径并作为下一步的输入；输出已存在时各步自动跳过（幂等）
    # 不传 exam_format —— 由题目文档内容自动推断
    run_parse_evaluation_pipeline(mineruparsed, mineruparsed)

def run_parse_evaluation_pipeline(question_input_document: str, answer_input_document: str, exam_format: ExamFormat | None = None) -> None:
    # 未显式指定时，从题目文档内容自动推断卷型
    if exam_format is None:
        exam_format = get_exam_format(question_input_document)
        print(f'inferred exam format: {exam_format.name}')
    questions_mainbody_md = GetQuestionsMainbodyStage(exam_format=exam_format).run(question_input_document)
    individual_question_csv = SplitQuestionMainbodyIntoIndividualQuestionsStage(exam_format=exam_format).run(questions_mainbody_md)
    SplitMineruParsedMdIntoAnswerSpansStage(exam_format=exam_format).run(
        answer_input_document, individual_question_csv)
    # joined_output_csv = os.path.join(
    #     os.path.dirname(individual_question_csv), joined_output_csv_basename)
    #
    # # prompts.csv 与 joined 输出同目录
    # prompts_output_csv = os.path.join(os.path.dirname(joined_output_csv), 'prompts.csv')
    # # keep the original metadata columns — prompts.csv is a superset of the joined
    # # CSV with the derived `id` and `prompt` fields added on top.
    # # 行 schema 统一定义在 dataclass_.py，全流水线复用（构造即校验、frozen 不可变）
    # prompts_output_columns = columns(PromptRow)
    #
    # os.makedirs(os.path.dirname(prompts_output_csv), exist_ok=True)
    # _rows_written = 0
    # with open(joined_output_csv, newline='') as _f_in, open(prompts_output_csv, 'w', newline='') as _f_out:
    #     _reader = csv.DictReader(_f_in)
    #     _writer = csv.DictWriter(_f_out, fieldnames=prompts_output_columns)
    #     _writer.writeheader()
    #     for _row in _reader:
    #         _writer.writerow(asdict(PromptRow(**_row)))
    #         _rows_written += 1
    # print(f'wrote {_rows_written} prompts to {prompts_output_csv}')


if __name__ == '__main__':
    main()
