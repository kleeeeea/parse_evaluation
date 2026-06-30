import csv
import os
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import List

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from dataclass_ import IndividualQuestionRow
from dataclass_ import LineTraceRecord
from dataclass_ import PipelineStageRunnerWithOutput
from dataclass_ import TraceAction
from dataclass_ import columns
from parse_evaluation._1_parse_answers import AnswerMainbodyFSM
from parse_evaluation.dataclass_ import NumberedItemWithContext
from parse_evaluation.exam_formats import ExamFormat
from tests.fixture._constants import mineruparsed

individual_question_output_csv_basename = 'individual_questions.csv'
question_fsm_trace_output_csv_basename = 'individual_questions_fsm_trace.csv'


@dataclass
class QuestionSpanState:
    context_lines: list[str] = field(default_factory=list)
    question_number: int | None = None
    last_itemnumber: int | None = None

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
        # 用实例属性 self.finished_lines 作为唯一的行游标（与父类 parse 一致），
        # 各 helper 返回的下一个下标赋回它即可。

        self.items: List[NumberedItemWithContext] = []
        self._updated_in_span_state = QuestionSpanState()

    def _maybe_set_span_last_itemnumber(self, line):
        """范围声明行（praxis 的 trigger 行本身 / plt 的 span 内 Directions 行）
        把当前 span 的最后一题设为 b。"""
        question_range = self.exam_format.maybe_get_span_first_last_itemnumber_from_item_starting_line(line)
        if not question_range:
            return
        first_q, last_q = question_range
        if first_q != self._next_item_number():
            print(f'WARNING: range line declares questions {first_q}…{last_q} '
                  f'but the next question should be {self._next_item_number()}')
            raise ValueError(line)
        self._updated_in_span_state.last_itemnumber = last_q

    def _is_valid_in_span_next_item_start_line(self, line):
        item_number = self.exam_format.maybe_get_item_number_from_item_starting_line(line)
        if item_number is None:
            return False
        if item_number != self._next_item_number():
            return False
        if self._updated_in_span_state.last_itemnumber is not None:
            if item_number > self._updated_in_span_state.last_itemnumber:
                return False
        return True

    def _process_line_for_streaming_questions(self, line):
        """Update passage/question state for one consumed span line."""
        if self._is_valid_in_span_next_item_start_line(line):
            if self._updated_in_span_state.context_lines:
                self._record_last_finished_line_action(
                        TraceAction.FINISH_QUESTION_CONTEXT)
            qnum = self.exam_format.maybe_get_item_number_from_item_starting_line(line)
            self._updated_in_span_state.question_number = qnum
            self.items.append(NumberedItemWithContext(
                    lines=[line],
                    number=qnum,
                    context='\n'.join(self._updated_in_span_state.context_lines).rstrip(),
            ))
            self.finished_lines_count += 1
            self._record_last_finished_line_action(
                    TraceAction.START_ITEM_INSIDE_SPAN)
        else:
            if self._updated_in_span_state.question_number is None:
                self._updated_in_span_state.context_lines.append(line)
                action = TraceAction.APPEND_TO_CONTEXT
            else:
                self.items[-1].lines.append(line)
                action = TraceAction.APPEND_TO_ITEM
            self.finished_lines_count += 1
            self._record_last_finished_line_action(action)

    def _consume(self, start_action: str, *, stop_at_question_start=True):
        """从当前 span 起点（self.finished_lines）吃到下一个 span 起点 / EOF，
        沿途处理 range 行并即时产出题目；self.finished_lines 推进到下一个待处理
        下标。行序列统一取 self.lines，不再当参数传。"""
        self._updated_in_span_state = QuestionSpanState()
        line = self.lines[self.finished_lines_count]
        self._process_line_for_streaming_questions(line)
        self._maybe_set_span_last_itemnumber(line)
        self._record_last_finished_line_action(start_action)
        while self.finished_lines_count < len(self.lines):
            line = self.lines[self.finished_lines_count]
            if self.exam_format.is_question_mainbody_end_line(line):
                break
            if self.exam_format.is_question_context_span_starting_line(line):
                break
            if self.exam_format.is_question_non_context_section_starting_line(line):
                break
            if stop_at_question_start and self.is_next_item_start(line):
                break
            self._maybe_set_span_last_itemnumber(line)
            self._process_line_for_streaming_questions(line)
        self._updated_in_span_state = QuestionSpanState()

    def _parse_till_context_item_finish(self):
        """passage-question span：从 trigger 行起，吃完整个 span（passage + 其各题）。"""
        self.has_mainbody_started = True
        self._consume(
                TraceAction.START_CONTEXT_ITEM_SPAN,
                stop_at_question_start=False)

    def parse_till_item_finish(self):
        """无 passage 的独立题：从题目行起，吃完这一道题。"""
        self.has_mainbody_started = True
        # 独立题内不会出现 range 行：praxis 的 range 行就是 trigger（会被
        # _is_span_start 先终止本 span）；plt 的 "Directions:" 行必跟在
        # Case History/Discrete trigger 之后，不会落在无-trigger 的独立题里。
        # 因此 _consume 沿途的 _apply_range 必是 no-op，不会推进首题号——断言之。
        self._consume(TraceAction.START_INDEPENDENT_ITEM)

    def parse(self, md_text) -> List[NumberedItemWithContext]:
        lines = md_text.splitlines()
        self.lines = lines

        while self.finished_lines_count < len(lines):
            line = lines[self.finished_lines_count]
            if (
                    self.has_mainbody_started
                    and self.exam_format.is_question_mainbody_end_line(line)
            ):
                self.finished_lines_count += 1
                self._record_last_finished_line_action(TraceAction.FINISH_MAINBODY)
                break
            if self.exam_format.is_question_context_span_starting_line(line):
                # passage-question span 起点；helper 内部推进 self.finished_lines
                # 行序列已在 self.lines 里，helper 直接读取，不再传 lines
                self._parse_till_context_item_finish()
            elif self.is_next_item_start(line):
                # 无 passage 的独立题起点；helper 内部推进 self.finished_lines
                self.parse_till_item_finish()
            else:
                # 既非 trigger 也非独立题起点——只可能是首个 span 之前的杂行。
                # mainbody 已被 _1 裁剪到首个 span 起点，正常不会走到这里
                # （range 行要么是 trigger=进入 span，要么在 span 内被 _consume 吞掉），
                # 跳过即可。
                # self.current_item_num = self.exam_format.get_possible_item_number(line)
                self.finished_lines_count += 1
                self._record_last_finished_line_action(
                        TraceAction.SKIP_INSIDE_MAINBODY
                        if self.has_mainbody_started
                        else TraceAction.SKIP_BEFORE_MAINBODY
                )
        print(f'FSM parsed {len(self.items)} questions '
              f'(1..{len(self.items)})')
        return self.items


class SplitQuestionMainbodyIntoIndividualQuestionsStage(PipelineStageRunnerWithOutput):
    # …/{dataset}/outputs/questions_mainbody.md -> …/{dataset}/outputs/individual_questions.csv
    output_basename = individual_question_output_csv_basename

    def _produce(self, output_path, current_questions_mainbody_md):
        with open(current_questions_mainbody_md) as f:
            md_text = f.read()
        fsm = QuestionMainbodyFSM(self.exam_format)
        questions = fsm.parse(md_text)

        rows = [IndividualQuestionRow(
                        question_number=str(item.number),
                        passage=item.context,
                        question='\n'.join(item.lines).strip(),
                        # 题目侧没有截图路径来源，恒取默认值（原 _3 同此）
                        original_page_screenshot_paths='[]',
                ) for item in questions]
        IndividualQuestionRow.write_csv(output_path, rows)
        trace_output_path = os.path.join(
                os.path.dirname(os.path.abspath(output_path)),
                question_fsm_trace_output_csv_basename,
        )
        with open(trace_output_path, 'w', newline='') as f:
            writer = csv.DictWriter(
                    f,
                    # 列名从 trace dataclass 字段自动导出，避免与 schema 漂移
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
