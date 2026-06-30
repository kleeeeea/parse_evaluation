import os

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from dataclass_ import AnswerSpanRow
from dataclass_ import EvaluationRecord
from dataclass_ import IndividualQuestionRow
from dataclass_ import ProblemAndAnswerRow
from dataclass_ import PipelineStageRunnerWithOutput
from parse_evaluation._1_parse_answers import SplitMineruParsedMdIntoAnswerSpansStage
from parse_evaluation._2_parse_questions import SplitQuestionMainbodyIntoIndividualQuestionsStage
from tests.fixture._constants import mineruparsed

joined_output_csv_basename = 'problems_and_answers.csv'



# def _load_by_question_number(csv_path):
#     rows = {}
#     with open(csv_path, newline='') as f:
#         for row in csv.DictReader(f):
#             try:
#                 rows[int(row['question_number'])] = row
#             except (KeyError, TypeError, ValueError):
#                 continue
#     return rows


# def _write_joined_output(individual_question_csv, answerspan_csv):
#     questions = _load_by_question_number(individual_question_csv)
#     answers = _load_by_question_number(answerspan_csv)
#     all_qnums = sorted(set(questions) | set(answers))
#     output_path = os.path.join(
#         os.path.dirname(os.path.abspath(individual_question_csv)),
#         joined_output_csv_basename,
#     )
#
#     with open(output_path, 'w', newline='') as f:
#         writer = csv.DictWriter(f, fieldnames=joined_output_columns)
#         writer.writeheader()
#         for qnum in all_qnums:
#             question = questions.get(qnum) or {}
#             answer = answers.get(qnum) or {}
#             writer.writerow(asdict(ProblemAndAnswerRow(
#                 question_number=str(qnum),
#                 passage=question.get('passage', ''),
#                 question=question.get('question', ''),
#                 answer=answer.get('answer', ''),
#                 question_page_screenshot_paths=question.get(
#                     'original_page_screenshot_paths', ''),
#                 answer_page_screenshot_paths=answer.get(
#                     'original_page_screenshot_paths', ''),
#             )))
#
#     missing_answers = sorted(set(questions) - set(answers))
#     missing_questions = sorted(set(answers) - set(questions))
#     print(f'wrote {len(all_qnums)} joined rows to {output_path}')
#     if missing_answers:
#         print(f'  questions without a matching answer: {missing_answers}')
#     if missing_questions:
#         print(f'  answers without a matching question: {missing_questions}')
#     return output_path

class JoinProblemsAndAnswersStage(PipelineStageRunnerWithOutput):
    """Outer-join the individual-questions CSV with the answer-spans CSV on
    question_number. Each output row pairs a question's passage + stem +
    choices with its corresponding answer + explanation.

    Rows present in only one input still get emitted (the other side's
    columns are left empty), so missing-side mismatches are visible in the
    output rather than silently dropped.

    双输入步骤：derive_output_path 按题目侧 csv（第一个输入）的目录定位输出。
    """
    # …/{mineru任务目录}/individual_questions.csv -> …/{mineru任务目录}/problems_and_answers.csv
    output_basename = joined_output_csv_basename

    def _produce(self, output_path, current_individual_question_csv, current_answerspan_csv):
        questions = IndividualQuestionRow.read_by_question_number(
                current_individual_question_csv)
        answers = AnswerSpanRow.read_by_question_number(current_answerspan_csv)
        all_qnums = sorted(set(questions) | set(answers))

        rows = []
        for qnum in all_qnums:
            q = questions.get(qnum)
            a = answers.get(qnum)
            rows.append(ProblemAndAnswerRow(
                question_number=str(qnum),
                passage=q.passage if q else '',
                question=q.question if q else '',
                answer=a.answer if a else '',
                question_page_screenshot_paths=(
                        q.original_page_screenshot_paths if q else ''),
                answer_page_screenshot_paths='',
            ))
        ProblemAndAnswerRow.write_csv(output_path, rows)
        evaluation_record_output_path = os.path.join(
                os.path.dirname(os.path.abspath(output_path)),
                'evaluation_records.jsonl',
        )
        EvaluationRecord.serialize_to_jsonl(
                [
                        EvaluationRecord.from_problem_and_answer_row(
                                row,
                                current_individual_question_csv=current_individual_question_csv,
                                current_answerspan_csv=current_answerspan_csv,
                                exam_format=self.exam_format,
                        )
                        for row in rows
                ],
                evaluation_record_output_path,
        )

        missing_answers = sorted(set(questions) - set(answers))
        missing_questions = sorted(set(answers) - set(questions))
        print(f'wrote {len(all_qnums)} joined rows to {output_path}')
        print(f'wrote {len(rows)} evaluation records to {evaluation_record_output_path}')
        if missing_answers:
            print(f'  questions without a matching answer: {missing_answers}')
        if missing_questions:
            print(f'  answers without a matching question: {missing_questions}')


if __name__ == '__main__':
    # 题目侧沿 _1_ -> _2_ 的 derive 链从输入 md 动态推导；
    # 答案侧用 _4_ 的 derive
    individual_question_output_csv = SplitQuestionMainbodyIntoIndividualQuestionsStage().derive_output_path(
        GetQuestionsMainbodyStage().derive_output_path(mineruparsed))
    JoinProblemsAndAnswersStage().run(
        individual_question_output_csv,
        SplitMineruParsedMdIntoAnswerSpansStage().derive_output_path(mineruparsed))
