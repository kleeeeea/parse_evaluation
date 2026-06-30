"""Frozen dataclasses 约束 pipeline 中每个 CSV 的行 schema。

- 列名由字段定义唯一导出（columns()），不再手维护字符串列表；
- Row(**row) 构造即校验：上游 CSV 多列/缺列/改名会直接 TypeError；
- frozen=True 保证行对象在写出前不会被改动。

CSV 落盘后所有值都是字符串，所以字段统一标注为 str，
构造方需自行 str() 数值字段（如 question_number）。
"""
import csv
from dataclasses import dataclass, fields
import os
import re
from typing import List

from exam_formats import ExamFormat
from parse_evaluation.exam_formats import PLT


def columns(row_cls) -> list[str]:
    """Row dataclass -> CSV 列名列表（即 DictWriter 的 fieldnames）。"""
    return [f.name for f in fields(row_cls)]


class _CsvRow:
    @classmethod
    def write_csv(cls, output_path, rows):
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns(cls))
            writer.writeheader()
            for row in rows:
                writer.writerow({
                        field: getattr(row, field)
                        for field in columns(cls)
                })


# 共享字段抽成 mixin 基类，避免在多个 Row 里重复定义同名字段。
# 注意：dataclass 按 MRO 逆序（基类在前）收集字段，所以子类的基类列表
# 要按「想要的列序」反着写，才能保持 CSV 列顺序不变。
@dataclass(frozen=True)
class _HasQuestionNumber:
    question_number: str

    @classmethod
    def read_by_question_number(cls, csv_path):
        # 主键列名取自本 mixin 声明的唯一字段，不硬编码 'question_number'
        # key_field = fields(_HasQuestionNumber)[0].name
        rows = {}
        with open(csv_path, newline='') as f:
            for row in csv.DictReader(f):
                # try:
                #     qnum = int(row[key_field])
                # except (KeyError, TypeError, ValueError):
                #     continue
                item = cls(**{field: row.get(field, '') for field in columns(cls)})
                rows[item.question_number] = item
        return rows


@dataclass(frozen=True)
class _HasPassageAndQuestion:
    passage: str
    question: str


@dataclass()
class NumberedItem:
    lines: List[str]
    number: int


@dataclass()
class NumberedItemWithContext(NumberedItem):
    context: str


class TraceAction:
    """FSM 逐行解析的事件名常量集合（answer/question FSM 共用），
    取代散落各处的 action 字符串字面量。值就是写进 trace/CSV 的字符串。"""
    # answer FSM (_1)
    START_ITEM = 'start_item'
    APPEND_TO_ITEM = 'append_to_item'
    FINISH_ITEM = 'finish_item'
    FINISH_MAINBODY = 'finish_mainbody'
    SKIP_BEFORE_MAINBODY = 'skip_before_mainbody'
    SKIP_INSIDE_MAINBODY = 'skip_inside_mainbody'
    # question FSM (_2)
    START_SPAN = 'start_span'
    START_INDEPENDENT_ITEM = 'start_independent_item'
    START_ITEM_INSIDE_SPAN = 'start_item_inside_span'
    APPEND_TO_CONTEXT = 'append_to_context'
    APPEND_TO_SPAN = 'append_to_span'
    FINISH_QUESTION_CONTEXT = 'finish_question_context'
    CLEAR_QUESTION_CONTEXT = 'clear_question_context'
    SKIP = 'skip'
    START_CONTEXT_ITEM_SPAN = 'start_context_item_span'


@dataclass
class LineTraceRecord:
    """FSM 逐行解析的一条 trace 记录（answer/question FSM 共用）。

    非 frozen：去重合并时要原地改 action/item_number，question FSM 还会补写
    expected_span_first_question 与真实调用栈。expected_span_first_question
    仅 question FSM 用到，answer FSM 留 None（其 CSV 不含该列）。
    """
    finished_lines_count: int  # 记录原始游标状态（0-based），不再派生 line_number
    included_items: int | str
    action: str
    line: str
    caller_function: str
    caller_location: str
    expected_span_first_question: int | None = None
    has_mainbody_started: bool = False


@dataclass(frozen=True)
class _HasAnswer:
    answer: str


@dataclass(frozen=True)
class IndividualQuestionRow(_HasPassageAndQuestion, _HasQuestionNumber, _CsvRow):
    """_2_ individual_questions.csv：一行 = 一道题（passage 随行冗余）。

    列序：question_number, passage, question, original_page_screenshot_paths
    """
    original_page_screenshot_paths: str


@dataclass(frozen=True)
class AnswerSpanRow(_HasAnswer, _HasQuestionNumber, _CsvRow):
    """_4_ answer_spans.csv：一行 = 一道题的答案+解析。

    列序：question_number, answer
    """

    @classmethod
    def from_numbered_item(cls, item: NumberedItem):
        return cls(
                answer='\n'.join(item.lines),
                question_number=item.number,
        )


@dataclass(frozen=True)
class ProblemAndAnswerRow(_HasAnswer, _HasPassageAndQuestion, _HasQuestionNumber, _CsvRow):
    """_5_ problems_and_answers.csv：题目与答案按题号 outer-join 后的一行。

    列序：question_number, passage, question, answer,
          question_page_screenshot_paths, answer_page_screenshot_paths
    """
    question_page_screenshot_paths: str
    answer_page_screenshot_paths: str


class PipelineStageRunnerWithOutput:
    """幂等的流水线步骤的公共骨架。

    run() 负责所有步骤共有的样板逻辑：推导输出路径 → 输出已存在则跳过
    → 建好输出目录 → 调用子类的 _produce() 真正干活 → 返回输出路径
    （各步返回的路径作为下一步的输入，输出已存在即跳过 = 幂等）。

    子类需要：
      - 设 output_basename（输出文件名，放在第一个输入的同目录下），
        或直接重写 derive_output_path() 自定义路径推导；
      - 实现 _produce(output_path, *inputs)：读入、计算、写出、打印汇总。
    """

    output_basename: str = None

    def __init__(self, exam_format: ExamFormat = None, skip_if_output_exists=True):
        if exam_format is None:
            from parse_evaluation.exam_formats import PLT
            exam_format = PLT()
        self.exam_format = exam_format
        self.skip_if_output_exists = skip_if_output_exists

    def derive_output_path(self, *inputs) -> str:
        # 默认：输出文件名放在第一个输入所在目录（全部 5 步都符合这一约定，
        # 包括 join 这种双输入步骤——它按题目侧 csv 的目录定位输出）
        return os.path.join(
                os.path.dirname(os.path.abspath(inputs[0])),
                self.output_basename)

    def _produce(self, output_path: str, *inputs) -> None:
        raise NotImplementedError

    def run(self, *inputs) -> str:
        output_path = self.derive_output_path(*inputs)
        if self.skip_if_output_exists and os.path.exists(output_path):
            print(f'skip: {output_path} already exists')
            return output_path
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        self._produce(output_path, *inputs)
        print('*' * 50 + f'''\n{output_path}\n^^^(output_path)^^^\n''' + '''\nat:\ngit_repos/llm_evals/parse_evaluation/dataclass_.py:106\n''' + '*' * 50)

        return output_path


# prompts.csv 目前是 joined CSV 的逐行透传，schema 相同，直接复用。
PromptRow = ProblemAndAnswerRow

import csv
import json
import os
from dataclasses import dataclass, asdict, fields
from typing import Any, Iterable

sample_record = {
        "id"         : "plt_5_9_001",
        "module"     : "科目二",
        "subject"    : None,
        "type"       : "单项选择题",
        "language"   : "en",
        "source_exam": "allen_plt_5_9_5623",
        "question"   : "Ms. Wright's effectiveness as a classroom manager is aided by her ability to remain aware of what's going on throughout her classroom at all times. In the language of Jacob Kounin, this ability is called teacher",
        "options"    : {
                "A": "wariness.",
                "B": "nosiness.",
                "C": "with-it-ness.",
                "D": "savvy."
        },
        "answer"     : "C",
        "explanation": "Kounin's idea of teacher \"with-it-ness\" refers to the ability to constantly be aware of what is going on in various parts of the classroom - a sort of \"sixth-sense\" about what each student needs or is doing.",
        "has_image"  : False
}


# define the data class that enforce the above field, and define a serialize method that output list of records to jsonl file


@dataclass
class EvaluationRecord:
    id: str
    question: str
    answer: str
    passage: str | None  # needed for questions that refer to contexts!
    explanation: str  #
    module: str  # e.g. subject 1, plt
    subject: str  # e.g. writing, math, biology
    type: str  # question type, e.g. multi-choice question, constructed response question
    language: str  # e.g. ch, en
    source_exam: str  # url of the origin edam
    source_exam_pdf: str  # url of the origin pdf file to cross check
    has_image: bool = False
    options: dict[str, str] | None = None  # optional field for the choices of the multi-choice question

    @staticmethod
    def _answer_looks_selected_response(answer: str) -> bool:
        answer = answer or ''

        def optional(pattern: str) -> str:
            return f'(?:{pattern})?'

        return any(
                re.search(pattern, answer, flags=re.IGNORECASE | re.MULTILINE)
                for pattern in (
                        r'^\s*'
                        + optional(r'##\s+')
                        + optional(r'\d+\.\s+')
                        + r'[A-Z]\s*(?:[.)]|$)',
                        r'\b'
                        + optional(r'correct\s+')
                        + r'answer\s+is\s+'
                        + optional(r'(choice|option)\s+')
                        + r'[A-Z]\b',
                        r'\b(choice|option)\s+[A-Z]\b',
                )
        )

    @classmethod
    def from_problem_and_answer_row(
            cls,
            row: ProblemAndAnswerRow,
            *,
            module: str = '',
            subject: str = '',
            question_type: str = '',
            language: str = 'en',
            source_exam: str = '',
            source_exam_pdf: str = '',
            has_image: bool = False,
            options: dict[str, str] | None = None,
            current_individual_question_csv=None,
            current_answerspan_csv=None,
            exam_format: ExamFormat = None,
    ) -> "EvaluationRecord":
        # 'current_individual_question_csv': '/Users/l/klee_code/git_repos/llm_evals/parse_evaluation/tests/fixture/praxis_plt_sections/plt_10/plt_10_question.pdf-6aee572b-1ff6-48fc-842c-c9e45f7bbdf0/individual_questions.csv',
        # 'current_answerspan_csv': '/Users/l/klee_code/git_repos/llm_evals/parse_evaluation/tests/fixture/praxis_plt_sections/plt_10/plt_10_answer.pdf-45672f27-4ab1-41f9-899e-f77371db0856/answer_spans.csv',
        # id 含路径信息：取数据集目录名（路径上两级，如 plt_10）作前缀，
        # 题号补零到 3 位，形如 plt_10_001，对齐 sample_record 的 'plt_5_9_001'。
        dataset = ''
        if current_individual_question_csv:
            # .../{dataset}/{mineru_task_dir}/individual_questions.csv
            dataset = os.path.basename(os.path.dirname(
                    os.path.dirname(current_individual_question_csv)))
        try:
            seq = f'{int(row.question_number):03d}'
        except (TypeError, ValueError):
            seq = str(row.question_number)

        record_id = f'parse_evaluation_{dataset}_{seq}' if dataset else f'question_{seq}'
        if language is None:
            if isinstance(exam_format, PLT):
                language = 'en'
        if subject is None:
            if isinstance(exam_format, PLT):
                subject = 'plt'
        if module is None:
            if isinstance(exam_format, PLT):
                module = 'plt'
        # source_exam / source_exam_pdf 从各自 csv 的父目录推导——该父目录是
        # mineru 任务目录（形如 plt_10_question.pdf-<uuid>），目录名即来源 PDF
        # 的标识：source_exam 取题目侧，source_exam_pdf 取答案侧（用于交叉核对）。
        # 显式传入时不覆盖。
        if not source_exam and current_individual_question_csv:
            source_exam = os.path.basename(
                    os.path.dirname(current_individual_question_csv))
        if not source_exam_pdf and current_answerspan_csv:
            source_exam_pdf = os.path.basename(
                    os.path.dirname(current_answerspan_csv))
        if not question_type:
            # 根据答案是否「选项字母（后接解释）」判定题型：
            #   选择题答案形如 "1. d. <解释>" 或 bare "C" / "C. <解释>"
            #   也可能写成 "The answer is C" / "correct answer is C"
            #   简答题答案形如 "## 1. Sample Response …"（题号后是普通词，非单字母选项）
            question_type = (
                    'selected_response'
                    if cls._answer_looks_selected_response(row.answer)
                    else 'constructed_response')
        return cls(
                id=record_id,
                question=row.question,
                answer=row.answer,
                passage=row.passage or None,
                explanation='',
                module=module,
                subject=subject,
                type=question_type,
                language=language,
                source_exam=source_exam,
                source_exam_pdf=source_exam_pdf,
                has_image=has_image,
                options=options,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationRecord":
        """Build a record from a dict, keeping only the declared fields."""
        allowed = {f.name for f in fields(cls)}
        missing = allowed - data.keys()
        if missing:
            raise ValueError(f"missing required fields: {sorted(missing)}")
        return cls(**{k: data[k] for k in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def serialize_to_jsonl(cls, records: Iterable["EvaluationRecord"], path: str) -> int:
        """Write records to a jsonl file (one JSON object per line). Returns count."""
        # materialize so we can iterate twice (jsonl + csv)
        records = list(records)
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False))
                f.write("\n")

        # also export the csv using the same filename, with suffix csv
        csv_path = os.path.splitext(path)[0] + ".csv"
        fieldnames = [f.name for f in fields(cls)]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                row = record.to_dict()
                # options is a dict; flatten to a JSON string for CSV
                if row.get("options") is not None:
                    row["options"] = json.dumps(row["options"], ensure_ascii=False)
                writer.writerow(row)

        return len(records)
