import csv
import importlib.util
import sys
from pathlib import Path

PARSE_EVALUATION_DIR = Path(__file__).resolve().parents[1]
if str(PARSE_EVALUATION_DIR) not in sys.path:
    sys.path.insert(0, str(PARSE_EVALUATION_DIR))

from parse_evaluation.exam_formats import PLT
from parse_evaluation.tests.fixture._constants import plt_8_answer_mineruparsed
from parse_evaluation.tests.fixture._constants import plt_8_question_mineruparsed

pipeline_spec = importlib.util.spec_from_file_location(
        'parse_evaluation_pipeline_impl',
        PARSE_EVALUATION_DIR / '_overall_pipeline.py',
)
pipeline_module = importlib.util.module_from_spec(pipeline_spec)
pipeline_spec.loader.exec_module(pipeline_module)
run_parse_evaluation_pipeline = (
        pipeline_module.run_parse_evaluation_pipeline)


def main():
    question_input = Path(plt_8_question_mineruparsed)
    answer_input = Path(plt_8_answer_mineruparsed)
    run_parse_evaluation_pipeline(
        str(question_input),
        str(answer_input),
        exam_format=PLT,
    )

    question_dir = question_input.parent
    answer_dir = answer_input.parent
    expected_outputs = (
        question_dir / 'questions_mainbody.md',
        question_dir / 'individual_questions.csv',
        answer_dir / 'answer_spans.csv',
        question_dir / 'problems_and_answers.csv',
    )
    for output in expected_outputs:
        assert output.is_file(), output

    with (question_dir / 'individual_questions.csv').open(newline='') as f:
        questions = list(csv.DictReader(f))
    with (answer_dir / 'answer_spans.csv').open(newline='') as f:
        answers = list(csv.DictReader(f))
    with (question_dir / 'problems_and_answers.csv').open(newline='') as f:
        joined = list(csv.DictReader(f))

    assert len(questions) == 36
    assert len(answers) == 36
    assert len(joined) == 36
    assert [row['question_number'] for row in joined] == [
        str(number) for number in range(1, 37)
    ]
    assert all(row['question'] for row in joined)
    assert all(row['answer'] for row in joined)
    print('PLT pipeline verified: 36 questions, answers, and joined rows')


if __name__ == '__main__':
    main()
