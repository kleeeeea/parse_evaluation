import csv
import os
import re
import sys
from dataclasses import asdict
from typing import Any, List

from dataclass_ import AnswerSpanRow
from dataclass_ import LineTraceRecord
from dataclass_ import Stage
from dataclass_ import columns
from exam_formats import ExamFormat
from parse_evaluation.dataclass_ import NumberedItem
from tests.fixture._constants import mineruparsed

answerspan_output_csv_basename = 'answer_spans.csv'
answer_fsm_trace_output_csv_basename = 'answer_spans_fsm_trace.csv'


# 一条答案的起始行由 exam_format.answer_header_re 决定：
# praxis: "1. d. Only choice d …"；plt 短答题: "## 1. Sample Response …"。

# Top-level markdown headers — used as section boundaries.

# write a simple FSM
class AnswerMainbodyFSM:

    def __init__(self, exam_format: ExamFormat = None, debug: bool = True):
        if exam_format is None:
            from parse_evaluation.exam_formats import PraxisReading
            exam_format = PraxisReading
        self.exam_format = exam_format

        self.next_itemspan_first_itemnumber = 1  # 下一个 span 的首题号（随 range 行推进）
        self.next_item_number = 1  # 全局连续题号（随每道题推进）
        self.current_item_number: int | None = None  # 当前正在解析的题号，供 _record_line 取用
        self.items:List[NumberedItem] = []  # 产出 [(qnum, passage, question_text)]
        self.line_trace: list[LineTraceRecord] = []

        self.is_verbose = debug
        self.has_mainbody_started = False               # 是否已开过 span（无-trigger 独立题的 WARNING 判据）

    def _record_line(self, action: str):
        # 行内容、行号、题号一律取内部状态，调用方只传 action
        line_index = self.current_line_number
        line = self.lines[line_index]
        line_number = line_index + 1
        item_number_value = (
                self.current_item_number
                if self.current_item_number is not None
                else len(self.items)
        )
        # also record callers stack info: function name, caller's filename and line number
        caller = sys._getframe(1)
        # 跳过 _record_* 包装层（如子类的 _record_source_line），定位真正的业务调用点
        while caller.f_back is not None and caller.f_code.co_name.startswith('_record_'):
            caller = caller.f_back
        caller_function = caller.f_code.co_name
        # 完整路径 + 行号，格式如 /abs/path/_1_parse_answers.py:83，便于点击跳转
        caller_location = f'{caller.f_code.co_filename}:{caller.f_lineno}'
        if self.line_trace and self.line_trace[-1].line_number == line_number:
            existing_actions = self.line_trace[-1].action.split('|')
            if action not in existing_actions:
                self.line_trace[-1].action += f'|{action}'
            if item_number_value and not self.line_trace[-1].item_number:
                self.line_trace[-1].item_number = item_number_value
            self.line_trace[-1].expected_item_number = (
                    self.next_itemspan_first_itemnumber)
            self.line_trace[-1].has_mainbody_started = (
                    self.has_mainbody_started)
            return

        self.line_trace.append(LineTraceRecord(
                line_number=line_number,
                expected_item_number=self.next_itemspan_first_itemnumber,
                item_number=item_number_value,  # 去掉这个没起作用的
                action=action,
                line=line,
                caller_function=caller_function,
                caller_location=caller_location,
                has_mainbody_started=self.has_mainbody_started,
        ))

    def is_item_start(self, line):
        # 答案主体起点：含 "Answers and Explanations" 的顶级标题
        return self.exam_format.get_possible_item_number(line) == self.next_itemspan_first_itemnumber

    def parse_till_item_finish(self, lines):
        """无 passage 的独立题：从题目行起，吃完这一道题。"""
        item_number = self.next_itemspan_first_itemnumber
        self.current_item_number = item_number
        self.next_itemspan_first_itemnumber += 1
        new_span = [lines[self.current_line_number]]
        self._record_line('start_item')
        # 用「预读下一行」推进：record finish_item 时 self.i 仍指向最后消费的行，
        # 因而无需把 line_index 传进 _record_line。
        while True:
            next_line_number = self.current_line_number + 1
            if (
                    next_line_number >= len(lines)
                    or self.exam_format.is_answer_mainbody_end_line(
                            lines[next_line_number])
                    or self.is_item_start(lines[next_line_number])
            ):
                self._record_line('finish_item')
                self.current_line_number = next_line_number
                break
            self.current_line_number = next_line_number
            new_span.append(lines[self.current_line_number])
            self._record_line('append_to_item')
        self.items.append(NumberedItem(
                content='\n'.join(new_span).strip(),
                number=item_number,
        ))

    def parse(self, md_text) -> List[NumberedItem]:
        """Parse answer lines into consecutively numbered answer items.

        ``line_trace`` keeps one record per consumed/skipped source line so
        parsing decisions can be inspected without changing the returned API.
        """
        if isinstance(md_text, list):
            lines = md_text
        else:
            lines = md_text.splitlines()
        self.lines = lines
        self.current_line_number = 0
        self.items = []
        self.line_trace = []
        self.next_itemspan_first_itemnumber = 1
        self.current_item_number = None
        self.has_mainbody_started = False
        while self.current_line_number < len(lines):
            line = lines[self.current_line_number]
            if (
                    self.has_mainbody_started
                    and self.exam_format.is_answer_mainbody_end_line(line)
            ):
                self._record_line('finish_mainbody')
                break
            if self.exam_format.get_possible_item_number(line) == self.next_itemspan_first_itemnumber:
                # 无 passage 的独立题起点
                if not self.has_mainbody_started:
                    self.has_mainbody_started = True
                self.parse_till_item_finish(lines)
            else:
                # 既非 trigger 也非独立题起点——只可能是首个 span 之前的杂行。
                # mainbody 已被 _1 裁剪到首个 span 起点，正常不会走到这里
                # （range 行要么是 trigger=进入 span，要么在 span 内被 _consume 吞掉），
                # 跳过即可。
                self._record_line(
                        'skip_inside_mainbody'
                        if self.has_mainbody_started
                        else 'skip_before_mainbody')
                self.current_line_number += 1
        return self.items


# def slice_mainbody(lines, is_start, is_end, *, default_start):
#     """切出文档主体的 [start, end) 行区间，供「题目主体」「答案主体」复用。
#
#     start：第一条 is_start(line) 命中的行；没命中则用 default_start
#     （题目主体取 0=文件头；答案主体取 len(lines)=空切片，没有答案区时）。
#     end：start 之后第一条 is_end(line) 命中的行；没命中则到文件尾。
#     再剥掉主体末尾的空行和孤立页码行（mineru 把页脚页码解析成单独一行，
#     否则会挂在最后一题/最后一条答案的尾部）。返回 (start, end) 下标。
#     """
#     start = next((i for i, l in enumerate(lines) if is_start(l)), default_start)
#     end = next((i for i in range(start, len(lines)) if is_end(lines[i])), len(lines))
#     while end > start and (not lines[end - 1].strip()
#                            or re.fullmatch(r'\s*\d+\s*', lines[end - 1])):
#         end -= 1
#     return start, end


def _split_markdown_into_answer_spans(
        md_text,
        exam_format: ExamFormat,
        expected_end_num=None,
        *,
        fsm_trace_output_csv=None):
    """先复用 slice_mainbody 切出答案主体（"Answers and Explanations" 标题起，
    到下一个非 Passage/Source 顶级标题止；没有答案区则空切片），再复用 _2 的
    split_into_items：答案号从 1 严格连续递增到 expected_end_num（题目数量），
    把答案解析里引用的题号挡在外面。expected_end_num 为 None 时不设上界。
    """
    lines = md_text.splitlines()
    fsm = AnswerMainbodyFSM(exam_format=exam_format)
    parse = fsm.parse(lines)
    if fsm_trace_output_csv:
        with open(fsm_trace_output_csv, 'w', newline='') as f:
            writer = csv.DictWriter(
                    f,
                    fieldnames=[
                            'line_number',
                            'expected_item_number',
                            'item_number',
                            'action',
                            'line',
                            'caller_function',
                            'caller_location',
                            'has_mainbody_started',
                    ],
                    # answer FSM 不用 expected_span_first_question 列，忽略之
                    extrasaction='ignore',
            )
            writer.writeheader()
            writer.writerows(asdict(r) for r in fsm.line_trace)
    if expected_end_num is not None:
        assert expected_end_num == len(parse)
    return parse
    # return [{'num': num, 'lines': item_lines}
    #         for num, item_lines in split_into_items(
    #             lines[start:end], _detect_answer_start,
    #             expected_start_num=1, expected_end_num=expected_end_num)]


# def _serialize_span(span):
#     return '\n'.join(span['lines']).strip()



class SplitMineruParsedMdIntoAnswerSpansStage(Stage):
    # …/{mineru任务目录}/full.md -> …/{mineru任务目录}/answer_spans.csv
    output_basename = answerspan_output_csv_basename

    def _produce(
            self, output_path, current_mineruparsed,
            individual_question_output_csv=None):
        with open(current_mineruparsed) as f:
            md_text = f.read()

        # 先读题目集合（若已产出）：既用于答案号上界（1..题目数量），也用于交叉核对。
        # 兼容旧的单输入调用：未显式传入时沿 _1_ -> _2_ 的 derive 链推导。
        # if individual_question_output_csv is None:
        # individual_question_output_csv = (
        #     SplitQuestionMainbodyIntoIndividualQuestionsStage()
        #     .derive_output_path(
        #         GetQuestionsMainbodyStage().derive_output_path(
        #             current_mineruparsed)))
        expected = set()
        if individual_question_output_csv and os.path.exists(individual_question_output_csv):
            with open(individual_question_output_csv) as f:
                for row in csv.DictReader(f):
                    try:
                        expected.add(int(row['question_number']))
                    except (KeyError, TypeError, ValueError):
                        pass

        fsm_trace_output_csv = os.path.join(
                os.path.dirname(os.path.abspath(output_path)),
                answer_fsm_trace_output_csv_basename,
        )
        spans = _split_markdown_into_answer_spans(
                md_text,
                self.exam_format,
                expected_end_num=len(expected) or None,
                fsm_trace_output_csv=fsm_trace_output_csv,
        )
        spans = [
                AnswerSpanRow(
                        answer=s.content,
                        question_number=s.number,
                ) for s in spans
        ]
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns(AnswerSpanRow))
            writer.writeheader()
            for s in spans:
                writer.writerow(asdict(s))
        print(f'wrote answer FSM trace to {fsm_trace_output_csv}')
        # # split_into_items 已保证答案号严格递增且唯一。
        # seen = {span['num'] for span in spans}
        #
        # missing = sorted(expected - seen)
        # extra = sorted(seen - expected) if expected else []
        # print(f'wrote {len(spans)} answer spans to {output_path}')
        # if missing:
        #     print(f'  missing answers for questions: {missing}')
        # if extra:
        #     print(f'  extra answers not in individual_questions.csv: {extra}')
        # if os.path.exists(individual_question_output_csv):
        #     _write_joined_output(individual_question_output_csv, output_path)


if __name__ == '__main__':
    SplitMineruParsedMdIntoAnswerSpansStage().run(mineruparsed)
