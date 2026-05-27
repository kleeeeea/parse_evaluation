import csv
import os

from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_problem_spans import mineruparsed
from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_problem_spans import questionspan_output_csv
from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_problem_spans import split_mineru_parsed_md_into_consecutive_problem_spans
from git_repos.parse_evaluation.split_consecutive_problem_spans_into_individual_questions import individual_question_output_csv
from git_repos.parse_evaluation.split_consecutive_problem_spans_into_individual_questions import split_consecutive_problem_spans_into_individual_questions
from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_answer_spans import answerspan_output_csv
from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_answer_spans import split_mineru_parsed_md_into_consecutive_answer_spans
from git_repos.parse_evaluation.join_problems_and_answers import joined_output_csv
from git_repos.parse_evaluation.join_problems_and_answers import join_problems_and_answers

split_mineru_parsed_md_into_consecutive_problem_spans(mineruparsed)
split_consecutive_problem_spans_into_individual_questions(questionspan_output_csv)
split_mineru_parsed_md_into_consecutive_answer_spans(mineruparsed)
join_problems_and_answers(individual_question_output_csv, answerspan_output_csv)
# for each row, format the data into a prompt by adapting the code below, also add an id field
def fmt_template(row: dict) -> str:
    """单项/多项选择题 — render a joined problems-and-answers row as a model prompt.

    The joined row already contains the passage block (trigger line + passage
    text + source citation) and the question block (stem + a–e choices), so
    we just stitch them together with the answer-format instruction.
    """
    lines = [row['passage'], "", row['question'], "", "请直接给出答案字母（如：A 或 AB），不需要解释。"]
    return "\n".join(lines)


prompts_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/prompts.csv'
prompts_output_columns = [
    'id',
    'prompt',
    'expected_answer',
    'question_page_screenshot_paths',
    'answer_page_screenshot_paths',
]

os.makedirs(os.path.dirname(prompts_output_csv), exist_ok=True)
_rows_written = 0
with open(joined_output_csv, newline='') as _f_in, open(prompts_output_csv, 'w', newline='') as _f_out:
    _reader = csv.DictReader(_f_in)
    _writer = csv.DictWriter(_f_out, fieldnames=prompts_output_columns)
    _writer.writeheader()
    for _row in _reader:
        _writer.writerow({
            'id': f"q{int(_row['question_number']):03d}",
            'prompt': fmt_template(_row),
            'expected_answer': _row['answer'],
            'question_page_screenshot_paths': _row['question_page_screenshot_paths'],
            'answer_page_screenshot_paths': _row['answer_page_screenshot_paths'],
        })
        _rows_written += 1
print(f'wrote {_rows_written} prompts to {prompts_output_csv}')

