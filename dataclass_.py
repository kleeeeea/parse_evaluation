"""Frozen dataclasses 约束 pipeline 中每个 CSV 的行 schema。

- 列名由字段定义唯一导出（columns()），不再手维护字符串列表；
- Row(**row) 构造即校验：上游 CSV 多列/缺列/改名会直接 TypeError；
- frozen=True 保证行对象在写出前不会被改动。

CSV 落盘后所有值都是字符串，所以字段统一标注为 str，
构造方需自行 str() 数值字段（如 question_number）。
"""
from dataclasses import dataclass, fields
import os

from exam_formats import ExamFormat



def columns(row_cls) -> list[str]:
    """Row dataclass -> CSV 列名列表（即 DictWriter 的 fieldnames）。"""
    return [f.name for f in fields(row_cls)]

# 共享字段抽成 mixin 基类，避免在多个 Row 里重复定义同名字段。
# 注意：dataclass 按 MRO 逆序（基类在前）收集字段，所以子类的基类列表
# 要按「想要的列序」反着写，才能保持 CSV 列顺序不变。
@dataclass(frozen=True)
class _HasQuestionNumber:
    question_number: str


@dataclass(frozen=True)
class _HasPassageAndQuestion:
    passage: str
    question: str


@dataclass(frozen=True)
class NumberedItem:
    content: str
    number: int

@dataclass(frozen=True)
class NumberedItemWithContext(NumberedItem):
    context: str


@dataclass
class LineTraceRecord:
    """FSM 逐行解析的一条 trace 记录（answer/question FSM 共用）。

    非 frozen：去重合并时要原地改 action/item_number，question FSM 还会补写
    expected_span_first_question 与真实调用栈。expected_span_first_question
    仅 question FSM 用到，answer FSM 留 None（其 CSV 不含该列）。
    """
    line_number: int
    expected_item_number: int
    item_number: int | str
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
class IndividualQuestionRow(_HasPassageAndQuestion, _HasQuestionNumber):
    """_2_ individual_questions.csv：一行 = 一道题（passage 随行冗余）。

    列序：question_number, passage, question, original_page_screenshot_paths
    """
    original_page_screenshot_paths: str


@dataclass(frozen=True)
class AnswerSpanRow(_HasAnswer, _HasQuestionNumber):
    """_4_ answer_spans.csv：一行 = 一道题的答案+解析。

    列序：question_number, answer
    """


@dataclass(frozen=True)
class ProblemAndAnswerRow(_HasAnswer, _HasPassageAndQuestion, _HasQuestionNumber):
    """_5_ problems_and_answers.csv：题目与答案按题号 outer-join 后的一行。

    列序：question_number, passage, question, answer,
          question_page_screenshot_paths, answer_page_screenshot_paths
    """
    question_page_screenshot_paths: str
    answer_page_screenshot_paths: str


class Stage:
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

    def __init__(self, exam_format: ExamFormat , skip_if_output_exists=True):
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
