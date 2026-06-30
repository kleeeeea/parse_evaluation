from pathlib import Path

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from _2_parse_questions import (
    SplitQuestionMainbodyIntoIndividualQuestionsStage,
)
from exam_formats import ExamFormat
from exam_formats import get_exam_format
from parse_evaluation._3_join_problems_and_answers import JoinProblemsAndAnswersStage
from parse_evaluation.exam_formats import EXAM_FORMAT_BY_NAME


def _infer_answer_input_document(question_input_document: str) -> str:
    question_path = Path(question_input_document)
    question_dir = question_path.parent
    question_dir_name = question_dir.name

    if 'question' not in question_dir_name:
        return str(question_path)

    parent_dir = question_dir.parent
    answer_prefix = question_dir_name.split('question', 1)[0] + 'answer'
    exact_answer_dir = parent_dir / question_dir_name.replace(
        'question', 'answer', 1)

    candidates = []
    exact_answer_path = exact_answer_dir / question_path.name
    if exact_answer_path.is_file():
        candidates.append(exact_answer_path)

    for sibling in parent_dir.iterdir():
        if not sibling.is_dir():
            continue
        if not sibling.name.startswith(answer_prefix):
            continue
        answer_path = sibling / question_path.name
        if answer_path.is_file() and answer_path not in candidates:
            candidates.append(answer_path)

    if len(candidates) == 1:
        return str(candidates[0])
    if candidates:
        raise ValueError(
            'multiple answer documents matched '
            f'{question_input_document}: {candidates}'
        )
    raise FileNotFoundError(
        'could not infer answer_input_document from '
        f'{question_input_document}'
    )



def run_parse_evaluation_pipeline(
    question_input_document: str,
    answer_input_document: str | None = None,
    exam_format_str: str | None = 'plt',
    exam_format: ExamFormat | None = None,
    *,
    skip_if_output_exists: bool = True,
) -> None:
    if (
        answer_input_document in EXAM_FORMAT_BY_NAME
        and exam_format_str == 'plt'
        and not Path(answer_input_document).exists()
    ):
        exam_format_str = answer_input_document
        answer_input_document = None

    if answer_input_document is None:
        answer_input_document = _infer_answer_input_document(
            question_input_document)
    # 允许传入卷型「类」（如 PLT），统一实例化——下游按实例方法调用 exam_format
    if isinstance(exam_format, type):
        exam_format = exam_format()
    if exam_format is None:
        exam_format = (
            EXAM_FORMAT_BY_NAME[exam_format_str] if exam_format_str else None
        )

    # 未显式指定时，从题目文档内容自动推断卷型
    if exam_format is None:
        exam_format = get_exam_format(question_input_document)
        print(f'inferred exam format: {exam_format.name}')
    from parse_evaluation._1_parse_answers import SplitMineruParsedMdIntoAnswerSpansStage
    answer_output_document = SplitMineruParsedMdIntoAnswerSpansStage(
        exam_format=exam_format,
        skip_if_output_exists=skip_if_output_exists,
    ).run(
        answer_input_document
    )
    # questions_mainbody_md = GetQuestionsMainbodyStage(
    #     exam_format=exam_format,
    #     skip_if_output_exists=skip_if_output_exists,
    # ).run(question_input_document)
    individual_question_csv = SplitQuestionMainbodyIntoIndividualQuestionsStage(
        exam_format=exam_format,
        skip_if_output_exists=skip_if_output_exists,
    ).run(question_input_document)
    JoinProblemsAndAnswersStage(
        exam_format=exam_format,
        skip_if_output_exists=skip_if_output_exists,
    ).run(individual_question_csv, answer_output_document)
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
    # print(f'wrote {_rows_written} prompts to {prompts_output_csv}')(




def main():
    question_input_document = '/Users/l/klee_code/git_repos/llm_evals/parse_evaluation/tests/fixture/praxis_plt_sections/plt_10/plt_10_question.pdf-6aee572b-1ff6-48fc-842c-c9e45f7bbdf0/full.md'
    # 每步返回输出路径并作为下一步的输入；输出已存在时各步自动跳过（幂等）
    # 不传 exam_format —— 由题目文档内容自动推断
    run_parse_evaluation_pipeline(
        question_input_document,
            skip_if_output_exists=False,
    )


if __name__ == '__main__':
    main()
