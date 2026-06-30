"""EvaluationRecord.from_problem_and_answer_row 的题型判定单测。

selected_response（选择题）：答案是选项字母（后接解释），如 "1. d. …" / bare "C"。
constructed_response（简答题）：题号后是普通词，如 "## 1. Sample Response …"。

直接运行即可（自带 sys.path 设置，无需 PYTHONPATH）：
    python parse_evaluation/tests/run_question_type_classification.py
"""
import sys
from pathlib import Path

PARSE_EVALUATION_DIR = Path(__file__).resolve().parents[1]
LLM_EVALS_DIR = PARSE_EVALUATION_DIR.parent
for p in (str(LLM_EVALS_DIR), str(PARSE_EVALUATION_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from parse_evaluation.dataclass_ import EvaluationRecord, ProblemAndAnswerRow


def _classify(ans):
    row = ProblemAndAnswerRow(
            question_number='1',
            passage='',
            question='q',
            answer=ans,
            question_page_screenshot_paths='',
            answer_page_screenshot_paths='',
    )
    return EvaluationRecord.from_problem_and_answer_row(row).type


CASES = [
    ('1. d. Only choice d sums up...', 'selected_response'),
    ('4. e. A strong title should...', 'selected_response'),
    ('## 1. Sample Response that receives a score of 2:', 'constructed_response'),
    ('C', 'selected_response'),
    ('C. with-it-ness.', 'selected_response'),
    ('The answer is C.', 'selected_response'),
    ('The correct answer is C because...', 'selected_response'),
    ('This item is best answered by option C.', 'selected_response'),
    ('A good teacher would always...', 'constructed_response'),
    ('1. First point. 2. Second point.', 'constructed_response'),
]


def main():
    failures = 0
    for ans, expected in CASES:
        got = _classify(ans)
        ok = got == expected
        failures += not ok
        print(('OK   ' if ok else 'FAIL ') + repr(ans[:40]) + ' -> ' + got)
    assert not failures, f'{failures} case(s) failed'
    print(f'all {len(CASES)} question_type cases passed')


if __name__ == '__main__':
    main()
