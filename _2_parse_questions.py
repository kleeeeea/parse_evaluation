import csv
import os
from dataclasses import asdict
from typing import List

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from dataclass_ import IndividualQuestionRow
from dataclass_ import LineTraceRecord
from dataclass_ import Stage
from dataclass_ import TraceAction
from dataclass_ import columns
from parse_evaluation._1_parse_answers import AnswerMainbodyFSM
from parse_evaluation.dataclass_ import NumberedItemWithContext
from parse_evaluation.exam_formats import ExamFormat
from tests.fixture._constants import mineruparsed

individual_question_output_csv_basename = 'individual_questions.csv'
question_fsm_trace_output_csv_basename = 'individual_questions_fsm_trace.csv'
output_csv_columns = columns(IndividualQuestionRow)

#
# def item_number_safe_search(exam_format: ExamFormat, line: str) -> int | None:
#     return exam_format.get_possible_item_number(line)
#


# example:
sample_questions_that_should_be_in_the_same_span_because_they_refer_to_the_same_passage = """
Use the following passage to answer questions 1 and 2.

Of the numerous American automotive pioneers, perhaps among the best known are Charles and Frank Duryea. Beginning their work of automobile building in Springfield,
5 Massachusetts, and, after much rebuilding, they constructed their first successful vehicle in 1892 and 1893. No sooner was this finished than Frank, working alone, began work on a second vehicle having a two-cylinder engine. With this
10 automobile, sufficient capital was attracted in 1895 to form the Duryea Motor Wagon Company in which both brothers were among the stockholders and directors. A short time after the formation of the company, this second
15 automobile was entered by the company in the Chicago Times-Herald automobile race on Thanksgiving Day, November 28, 1895, where Frank Duryea won a victory over the other five contestants—two electric automobiles and
20 three Benz machines imported from Germany.

Source: Excerpt from The 1893 Duryea Automobile by Don H. Berkebile.

Which of the following is the best summary of the passage?
a. There were many automotive pioneers in America, but the best known were the brothers Charles and Frank Duryea, who began building automobiles in Springfield, Massachusetts. b. Charles and Frank Duryea were among the best-known American automotive pioneers, but Frank was more famous than his brother Charles because Frank won the Chicago Times-Herald automobile race.
c. On Thanksgiving Day, November 28, 1895, Frank Duryea won the Chicago Times-Herald automobile race over five other contestants: two electric automobiles and three Benz machines from Germany.
d. Charles and Frank Duryea were pioneering automobile builders, and Frank developed a profitable two-cylinder engine vehicle with which he won the Chicago Times-Herald automobile race.
e. Although Frank Duryea developed a two-cylinder engine vehicle, both he and his brother Charles profited from it because it earned them the capital to start the Duryea Motor Wagon Company.

In the passage, the author describes the kinds of cars Frank Duryea defeated in the Chicago Times-Herald automobile race in order to
a. show that the best automobiles in the world are built in Springfield, Massachusetts.
b. imply that he would later develop an electric car for the Duryea Motor Wagon Company.
c. indicate that the quality of automobiles being developed in Europe was very poor at the time.
d. suggest that the kind of car he drove is what helped him win the race.
e. help the reader understand the differences between two-cylinder vehicles and electric automobiles.
"""
# split the mineruparsed data into csvs and save it into output_csv

# 卷型相关的正则（trigger / 题目行 / 范围声明行）统一定义在 exam_formats.py。

# enforce passing in expected_end_num




class QuestionMainbodyFSM(AnswerMainbodyFSM):
    """逐行扫描 questions mainbody，直接产出一道道单题（passage 随题冗余）。

    把原来分两步的逻辑合进一个有状态机：
    - 切 span（原 _2）：questions_span_trigger_res（一组 trigger，命中任一）是
      span 的显式起点（praxis 的 "Use the following passage…" 行；plt 的
      "## Case History N" / "## Discrete Multiple-Choice Questions" 节标题）；之后所有行都留在
      当前 span 里直到下一个 trigger。范围声明行（question_range_re，praxis
      的 trigger 行本身 / plt 的 Directions 行）声明 [a, b]，把「下一个 span
      的首题号」推到 b+1；题号 == 该首题号的题目行意味着上一个 span 结束、
      一道无 trigger 的独立题开新 span（正常不触发，触发则打 WARNING）。
    - span 内分题（原 _3）：每关闭一个 span，用「全局连续题号」识别其中各题
      的起始行（parse_item），首题之前的行即该 span 的 passage，passage 随
      每道题冗余写出。两个计数器在 span 边界处相等，互不影响。

    输入可以是 full markdown，也可以是 get_questions_mainbody 产出的已裁剪主体。
    parse() 会在 FSM 内跳过题目主体前的前言，并在题目主体结束标题处停止。
    """

    def __init__(self, exam_format: ExamFormat = None, debug: bool = True):
        super().__init__(
                exam_format=exam_format,
                debug=debug,
        )
        self.items:List[NumberedItemWithContext] = []  # 产出 [(qnum, passage, question_text)]
        self.next_item_number = 1
        # 用实例属性 self.finished_lines 作为唯一的行游标（与父类 parse 一致），
        # 各 helper 返回的下一个下标赋回它即可。

    def _record_last_finished_line_action(self, action: str):
        super()._record_last_finished_line_action(action)
        rec = self.line_trace[-1]
        rec.next_itemspan_first_itemnumber = self.next_item_number
        rec.expected_span_first_question = self.next_itemspan_first_itemnumber

    def _is_span_start(self, line):
        """span 的两种起点：trigger 行（命中任一 trigger），或题号 == 下一 span
        首题号的无-trigger 独立题。"""
        if self.exam_format.is_question_context_start_line(line):
            return True
        return self.exam_format.get_possible_item_number(line) == self.next_itemspan_first_itemnumber

    def _maybe_update_next_span_first_question(self, line):
        """范围声明行（praxis 的 trigger 行本身 / plt 的 span 内 Directions 行）
        把下一 span 首题号推到 b+1。"""
        question_range = self.exam_format.get_possible_question_range(line)
        if not question_range:
            return
        first_q, last_q = question_range
        if first_q != self.next_itemspan_first_itemnumber:
            print(f'WARNING: range line declares questions {first_q}…{last_q} '
                  f'but the next span should start at question {self.next_itemspan_first_itemnumber}')
            raise ValueError(line)
        self.next_itemspan_first_itemnumber = last_q + 1

    def _begin_streaming_span(self):
        self._span_item_count_before = len(self.items)
        self._span_context_lines = []
        self._span_current_question_lines = []
        self._span_current_question_number = None
        self._span_last_question_number = None

    def _set_span_end_from_range_line(self, old_next_itemspan_first_itemnumber):
        if self.next_itemspan_first_itemnumber != old_next_itemspan_first_itemnumber:
            self._span_last_question_number = self.next_itemspan_first_itemnumber - 1

    def _is_expected_question_start(self, line):
        qnum = self.exam_format.get_possible_item_number(line)
        if qnum != self.next_item_number:
            return False
        if (
                self._span_last_question_number is not None
                and qnum > self._span_last_question_number
        ):
            return False
        return True

    def _finish_current_streaming_question(self):
        if self._span_current_question_number is None:
            return
        self.items.append(NumberedItemWithContext(
                lines=self._span_current_question_lines,
                number=self._span_current_question_number,
                context='\n'.join(self._span_context_lines).rstrip(),
        ))
        self._span_current_question_lines = []
        self._span_current_question_number = None

    def _process_line_for_streaming_questions(self, line):
        """Update passage/question state for one consumed span line.

        Returns True when this line starts a newly attached question, so the
        caller can merge ATTACH_QUESTION_CONTEXT into this line's trace record.
        """
        if not self._is_expected_question_start(line):
            if self._span_current_question_number is None:
                self._span_context_lines.append(line)
            else:
                self._span_current_question_lines.append(line)
            return False

        if self._span_current_question_number is not None:
            self._finish_current_streaming_question()
        elif self._span_context_lines:
            self.current_item_number = self.exam_format.get_possible_item_number(
                    self.lines[self.finished_lines - 1])
            self._record_last_finished_line_action(
                    TraceAction.FINISH_QUESTION_CONTEXT)

        qnum = self.exam_format.get_possible_item_number(line)
        self._span_current_question_number = qnum
        self._span_current_question_lines = [line]
        self.next_item_number += 1
        return True

    def _finish_streaming_span(self):
        self._finish_current_streaming_question()
        if (
                len(self.items) > self._span_item_count_before
                and self._span_context_lines
        ):
            self.current_item_number = self.items[-1].number
            self._record_last_finished_line_action(
                    TraceAction.CLEAR_QUESTION_CONTEXT)
        self.next_itemspan_first_itemnumber = max(
                self.next_itemspan_first_itemnumber,
                self.next_item_number,
        )

    def _consume(self, lines, *, stop_at_question_start=True):
        """从当前 span 起点（self.finished_lines）吃到下一个 span 起点 / EOF，
        沿途处理 range 行。返回 span 的行列表；self.finished_lines 推进到
        下一个待处理下标。"""
        self._begin_streaming_span()
        line = lines[self.finished_lines]
        span = [line]
        start_action = (
                TraceAction.START_SPAN
                if self.exam_format.is_question_context_start_line(line)
                else TraceAction.START_INDEPENDENT_ITEM
        )
        self.current_item_number = self.exam_format.get_possible_item_number(line)
        attached_question = self._process_line_for_streaming_questions(line)
        old_next_itemspan_first_itemnumber = self.next_itemspan_first_itemnumber
        self._maybe_update_next_span_first_question(line)
        self._set_span_end_from_range_line(old_next_itemspan_first_itemnumber)
        self.finished_lines += 1
        self._record_last_finished_line_action(start_action)
        if attached_question:
            self.current_item_number = self._span_current_question_number
            self._record_last_finished_line_action(
                    TraceAction.ATTACH_QUESTION_CONTEXT)
        while self.finished_lines < len(lines):
            line = lines[self.finished_lines]
            if self.exam_format.is_question_mainbody_end_line(line):
                break
            if self.exam_format.is_question_context_start_line(line):
                break
            if stop_at_question_start and self._is_span_start(line):
                break
            span.append(line)
            action = (
                    TraceAction.APPEND_ITEM_START_TO_SPAN
                    if self.exam_format.get_possible_item_number(line)
                    else TraceAction.APPEND_TO_SPAN
            )
            self.current_item_number = self.exam_format.get_possible_item_number(line)
            attached_question = self._process_line_for_streaming_questions(line)
            old_next_itemspan_first_itemnumber = self.next_itemspan_first_itemnumber
            self._maybe_update_next_span_first_question(line)
            self._set_span_end_from_range_line(old_next_itemspan_first_itemnumber)
            self.finished_lines += 1
            self._record_last_finished_line_action(action)
            if attached_question:
                self.current_item_number = self._span_current_question_number
                self._record_last_finished_line_action(
                        TraceAction.ATTACH_QUESTION_CONTEXT)
        self._finish_streaming_span()
        return span

    def _emit_span(self, span_lines):
        """span 关闭：非空则可选 debug 打印。题目产出已在 _consume 中完成。"""
        text = '\n'.join(span_lines).strip()
        if not text:
            return
        if self.is_verbose:
            print('=' * 100)
            print(text)

    def _parse_till_context_item_finish(self, lines):
        """passage-question span：从 trigger 行起，吃完整个 span（passage + 其各题）。"""
        self.has_mainbody_started = True
        span = self._consume(lines, stop_at_question_start=False)
        next_i = self.finished_lines  # _consume 推进后的下一待处理行
        self._emit_span(span)
        # debug 打印不应改变游标；复位到 span 之后的待处理行
        self.finished_lines = next_i

    def parse_till_item_finish(self, lines):
        """无 passage 的独立题：从题目行起，吃完这一道题。"""
        if self.has_mainbody_started:
            print(f'WARNING: question {self.next_itemspan_first_itemnumber} appeared '
                  f'without a preceding trigger line — if it has a '
                  f'passage, the passage stayed in the previous span')
        self.has_mainbody_started = True
        self.next_itemspan_first_itemnumber += 1
        # 独立题内不会出现 range 行：praxis 的 range 行就是 trigger（会被
        # _is_span_start 先终止本 span）；plt 的 "Directions:" 行必跟在
        # Case History/Discrete trigger 之后，不会落在无-trigger 的独立题里。
        # 因此 _consume 沿途的 _apply_range 必是 no-op，不会推进首题号——断言之。
        before = self.next_itemspan_first_itemnumber
        span = self._consume(lines)
        next_i = self.finished_lines  # _consume 推进后的下一待处理行
        assert self.next_itemspan_first_itemnumber == before, (
            f'independent question span unexpectedly contained a range line: {span!r}')
        self._emit_span(span)
        # debug 打印不应改变游标；复位到下一待处理行
        self.finished_lines = next_i

    def parse(self, md_text):
        lines = md_text.splitlines()
        self.lines = lines
        self.items = []
        self.line_trace = []
        self.next_item_number = 1
        self.next_itemspan_first_itemnumber = 1
        self.current_item_number = None
        self.has_mainbody_started = False
        self.finished_lines = 0

        while self.finished_lines < len(lines):
            line = lines[self.finished_lines]
            if (
                    self.has_mainbody_started
                    and self.exam_format.is_question_mainbody_end_line(line)
            ):
                self.current_item_number = self.exam_format.get_possible_item_number(line)
                self.finished_lines += 1
                self._record_last_finished_line_action(TraceAction.FINISH_MAINBODY)
                break
            if self.exam_format.is_question_context_start_line(line):
                # passage-question span 起点；helper 内部推进 self.finished_lines
                self._parse_till_context_item_finish(lines)
            elif self.exam_format.get_possible_item_number( line) == self.next_itemspan_first_itemnumber:
                # 无 passage 的独立题起点；helper 内部推进 self.finished_lines
                self.parse_till_item_finish(lines)
            else:
                # 既非 trigger 也非独立题起点——只可能是首个 span 之前的杂行。
                # mainbody 已被 _1 裁剪到首个 span 起点，正常不会走到这里
                # （range 行要么是 trigger=进入 span，要么在 span 内被 _consume 吞掉），
                # 跳过即可。
                self.current_item_number = self.exam_format.get_possible_item_number(line)
                self.finished_lines += 1
                self._record_last_finished_line_action(
                        TraceAction.SKIP_INSIDE_MAINBODY
                        if self.has_mainbody_started
                        else TraceAction.SKIP_BEFORE_MAINBODY)
        print(f'FSM parsed {len(self.items)} questions '
              f'(1..{self.next_item_number - 1})')
        return self.items


class SplitQuestionMainbodyIntoIndividualQuestionsStage(Stage):
    # …/{dataset}/outputs/questions_mainbody.md -> …/{dataset}/outputs/individual_questions.csv
    output_basename = individual_question_output_csv_basename

    def _produce(self, output_path, current_questions_mainbody_md):
        with open(current_questions_mainbody_md) as f:
            md_text = f.read()
        fsm = QuestionMainbodyFSM(self.exam_format)
        questions = fsm.parse(md_text)
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=output_csv_columns)
            writer.writeheader()
            for item in questions:
                writer.writerow(asdict(IndividualQuestionRow(
                    question_number=str(item.number),
                    passage=item.context,
                    question='\n'.join(item.lines).strip(),
                    # 题目侧没有截图路径来源，恒取默认值（原 _3 同此）
                    original_page_screenshot_paths='[]',
                )))
        trace_output_path = os.path.join(
                os.path.dirname(os.path.abspath(output_path)),
                question_fsm_trace_output_csv_basename,
        )
        with open(trace_output_path, 'w', newline='') as f:
            writer = csv.DictWriter(
                    f,
                    # 列名从 LineTraceRecord 字段自动导出，避免与 dataclass 漂移
                    fieldnames=columns(LineTraceRecord),
            )
            writer.writeheader()
            writer.writerows(asdict(r) for r in fsm.line_trace)
        print(f'wrote {len(questions)} questions to {output_path}')
        print(f'wrote question FSM trace to {trace_output_path}')

if __name__ == '__main__':
    # 从 fixture 的输入 md 沿 _1_ 的 derive 推出 questions_mainbody.md
    SplitQuestionMainbodyIntoIndividualQuestionsStage().run(
        GetQuestionsMainbodyStage().derive_output_path(mineruparsed))
