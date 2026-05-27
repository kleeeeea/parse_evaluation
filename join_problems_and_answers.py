import csv
import os

from git_repos.parse_evaluation.split_consecutive_problem_spans_into_individual_questions import individual_question_output_csv
from git_repos.parse_evaluation.split_mineru_parsed_md_into_consecutive_answer_spans import answerspan_output_csv

joined_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/problems_and_answers.csv'
joined_output_columns = [
    'question_number',
    'passage',
    'question',
    'answer',
    'question_page_screenshot_paths',
    'answer_page_screenshot_paths',
]


def _load_by_question_number(csv_path):
    """Load a CSV keyed by integer question_number."""
    by_q = {}
    with open(csv_path, newline='') as f:
        for row in csv.DictReader(f):
            try:
                qnum = int(row['question_number'])
            except (KeyError, TypeError, ValueError):
                continue
            by_q[qnum] = row
    return by_q


def join_problems_and_answers(current_individual_question_csv, current_answerspan_csv):
    """Outer-join the individual-questions CSV with the answer-spans CSV on
    question_number. Each output row pairs a question's passage + stem +
    choices with its corresponding answer + explanation.

    Rows present in only one input still get emitted (the other side's
    columns are left empty), so missing-side mismatches are visible in the
    output rather than silently dropped.
    """
    questions = _load_by_question_number(current_individual_question_csv)
    answers = _load_by_question_number(current_answerspan_csv)
    all_qnums = sorted(set(questions) | set(answers))

    out_dir = os.path.dirname(joined_output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(joined_output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=joined_output_columns)
        writer.writeheader()
        for qnum in all_qnums:
            q = questions.get(qnum) or {}
            a = answers.get(qnum) or {}
            writer.writerow({
                'question_number': qnum,
                'passage': q.get('passage', ''),
                'question': q.get('question', ''),
                'answer': a.get('answer', ''),
                'question_page_screenshot_paths': q.get('original_page_screenshot_paths', ''),
                'answer_page_screenshot_paths': a.get('original_page_screenshot_paths', ''),
            })

    missing_answers = sorted(set(questions) - set(answers))
    missing_questions = sorted(set(answers) - set(questions))
    print(f'wrote {len(all_qnums)} joined rows to {joined_output_csv}')
    if missing_answers:
        print(f'  questions without a matching answer: {missing_answers}')
    if missing_questions:
        print(f'  answers without a matching question: {missing_questions}')


if __name__ == '__main__':
    join_problems_and_answers(individual_question_output_csv, answerspan_output_csv)
