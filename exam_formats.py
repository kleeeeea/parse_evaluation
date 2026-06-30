"""卷型相关的解析规则，参数化成 frozen dataclass。

pipeline 各步（_1_/_2_/_3_/_4_）只依赖 ExamFormat 字段，
新增卷型时在这里加一个实例即可，不需要复制脚本。
"""
import re
from dataclasses import dataclass
from functools import lru_cache


@lru_cache(maxsize=None)
def _re_compile(expr: str | re.Pattern, flags=0) -> re.Pattern | None:
    if isinstance(expr, str):
        return re.compile(expr, flags) if expr else None
    else:
        return expr


@dataclass(frozen=True)
class ExamFormat:
    name: str = ''

    def is_answer_mainbody_start_line(self, line):
        # # 答案区里一条答案的起始行（plt 的短答题答案是 "## 1. Sample Response…" 二级标题）
        # answer_mainbody_start_re: re.Pattern
        for r in [
                r'^[ \t]*(\d+)\.\s',
        ]:
            m = _re_compile(r).match(line)
            if m:
                return True
        return bool(self.maybe_get_item_number_from_item_starting_line(line))

    def is_answer_mainbody_end_line(self, line):
        # 答案主体终点：下一个顶级标题——但 Passage/Source 子标题不算（留在答案内），
        # 另一段 "Answers and Explanations" 标题也不算（同属答案区）
        m = _re_compile(r'^#\s+(.*)$').match(line)
        if not m:
            return False
        header_text = m.group(1).strip()
        # Sub-labels that may appear inside an answer section and should NOT end it.
        if _re_compile(r'Answers and Explanations', re.IGNORECASE).search(header_text):
            return False
        # A top-level header that contains this phrase opens the answer section.
        return not _re_compile(r'^\s*(Passage|Source)\s+\d+\s*$', re.IGNORECASE).match(header_text)

    def maybe_get_item_number_from_item_starting_line(self, line: str) -> int | None:
        """题目行 -> 题号；非题目行 -> None。

        question_line_re 可能是多分支正则（如 plt 的 "## Question N" 与 "N. "），
        题号取第一个非 None 的捕获组。
        """
        # # 题目行；题号取第一个非 None 捕获组（见 question_number_safe_search）
        # question_line_re: re.Pattern
        # answer_span_trigger_res: tuple[re.Pattern, ...] | None = None
        for r in [
                # 短答题题号在二级标题里（"## Question 19"），选择题是 "N. " 行
                # passage 行号边注（"5 Massachusetts, and…"）没有点号，不会误中
                r'^##\s+Question\s+(\d+)\s*$',
                # 选择题答案："7. B …"
                r'^\s*(\d+)\.\s',
                # 短答题答案："## 1. Sample Response that receives a score of 2:"；
                # 选择题答案："7. B …"
                r'^(?:##\s+)?(\d+)\.\s',
        ]:
            m = _re_compile(r).match(line)
            if m:
                g = next((g for g in m.groups() if g is not None), None)
                if g is not None:
                    return int(g)

    def is_question_mainbody_end_line(self, line: str) -> bool | None:
        # # 题目主体的终止标题；None 表示题目文档没有答案区（题/答分开两份 PDF），主体到文件尾
        return any(_re_compile(r).match(line) for r in [
                # 题目 PDF 末尾可能附答题卡，部分 constructed-response PDF 也会在
                # 题目后直接附答案解析；这些标题之后都不是题目主体。

                _re_compile(
                        r'^##\s+(?:Diagnostic Test Form\b|ANSWERS AND EXPLANATIONS\b)',
                        re.IGNORECASE,
                ),
                _re_compile(r'^#\s+.*Answers and Explanations', re.IGNORECASE),
        ])

    def is_question_context_span_starting_line(self, line: str) -> bool:
        # 开启一个新 span 的行——可有多种 trigger，命中任一即算 span 起点
        # （praxis: "Use the following passage…"；plt: "## Case History N"
        # 与 "## Discrete Multiple-Choice Questions" 两种节标题）。
        # questions_span_trigger_res: tuple[re.Pattern, ...]
        return any(_re_compile(r).match(line) for r in [
                r'^##\s+Case History \d+\s*$',
                _re_compile(
                        r'^##\s+Constructed-Response Questions:\s+Case History #?\d+\s*$',
                        re.IGNORECASE,
                ),
                _re_compile(r'^##\s+Discrete Multiple-Choice Questions\s*$'),
                _re_compile(r'^\s*Use the following passage', re.IGNORECASE)
        ])

    def maybe_get_span_first_last_itemnumber_from_item_starting_line(self, line: str) -> bool:
        # # 声明题号范围的行：group(1)=起始题号，group(2)=结束题号（可缺省=单题）。
        # # praxis 在 trigger 行上（"… questions 50 through 53."），
        # # plt 在 Directions 行上（"Directions: Questions 7–18 are not related…"）。
        # # 必须锚定到该行特有的前缀，避免普通正文误中。
        # question_range_re: re.Pattern

        # "Directions: Questions 1 through 3 …" / "Directions: Questions 7–18 …"
        for pattern in (
                    re.compile(
                            r'^Directions:.*?Questions?\s+(\d+)\s*(?:through|–|—|-)\s*(\d+)',
                            re.IGNORECASE,
                    ),
                    re.compile(
                            r'^\s*Use the following passage.*?questions?\s+(\d+)'
                            r'(?:\s+(?:and|through)\s+(\d+))?',
                            re.IGNORECASE,
                    ),
        ):
            match = pattern.search(line)
            if match:
                first_q = int(match.group(1))
                last_q = int(match.group(2) or match.group(1))
                return first_q, last_q
        return None


@dataclass(frozen=True)
class PraxisReading(ExamFormat):
    name: str = 'praxis_reading'


@dataclass(frozen=True)
class PLT(ExamFormat):
    name: str = 'plt'


# 已知卷型登记表；get_exam_format 按内容在其中择一。新增卷型加到这里即可。
EXAM_FORMATS = (PraxisReading, PLT)


def get_exam_format(question_input_path) -> ExamFormat:
    """根据输入路径推断卷型。

    路径里出现哪种卷型的 name 就用哪种（dataset 目录命名约定，如
    'praxis_reading_1' / 'plt_8'）；都不匹配时回退 PRAXIS_READING。
    """
    path = question_input_path.lower()
    return next((fmt for fmt in EXAM_FORMATS if fmt.name in path), PLT)()


EXAM_FORMAT_BY_NAME = {fmt.name: fmt() for fmt in EXAM_FORMATS}
