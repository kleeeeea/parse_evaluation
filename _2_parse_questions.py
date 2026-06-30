import csv
import os
import re
from dataclasses import asdict

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from dataclass_ import IndividualQuestionRow
from dataclass_ import Stage
from dataclass_ import columns
from parse_evaluation._1_parse_answers import AnswerMainbodyFSM
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

    输入是 get_questions_mainbody 产出的已裁剪主体：无前言、无答案区。
    """

    def __init__(self, exam_format: ExamFormat = None, debug: bool = True):
        super().__init__(
                exam_format=exam_format,
                debug=debug,
        )
        self.next_span_first_question = 1

    def _record_line(self, action: str):
        super()._record_line(action)
        rec = self.line_trace[-1]
        rec.expected_item_number = self.next_item_number
        rec.expected_span_first_question = self.next_span_first_question

    def _is_span_start(self, line):
        """span 的两种起点：trigger 行（命中任一 trigger），或题号 == 下一 span
        首题号的无-trigger 独立题。"""
        if self.exam_format.is_question_context_start_line(line):
            return True
        return self.exam_format.get_possible_item_number(line) == self.next_span_first_question

    def _apply_range(self, line):
        """范围声明行（praxis 的 trigger 行本身 / plt 的 span 内 Directions 行）
        把下一 span 首题号推到 b+1。"""
        question_range = self.exam_format.get_possible_question_range(line)
        if not question_range:
            return
        first_q, last_q = question_range
        if first_q != self.next_span_first_question:
            print(f'WARNING: range line declares questions {first_q}…{last_q} '
                  f'but the next span should start at question {self.next_span_first_question}')
            raise ValueError(line)
        self.next_span_first_question = last_q + 1

    def _consume(self, lines, i, *, stop_at_question_start=True):
        """从 span 起点 i 吃到下一个 span 起点 / EOF，沿途处理 range 行。
        返回 (span 的行列表, 下一个待处理下标)。"""
        span = [lines[i]]
        start_action = (
                'start_span'
                if self.exam_format.is_question_context_start_line(lines[i])
                else 'start_independent_item'
        )
        self.current_line_number = i
        self.current_item_number = self.exam_format.get_possible_item_number(
                lines[i])
        self._record_line(start_action)
        self._apply_range(lines[i])
        i += 1
        while i < len(lines):
            if self.exam_format.is_question_context_start_line(lines[i]):
                break
            if stop_at_question_start and self._is_span_start(lines[i]):
                break
            span.append(lines[i])
            action = (
                    'append_item_start_to_span'
                    if self.exam_format.get_possible_item_number(lines[i])
                    else 'append_to_span'
            )
            self.current_line_number = i
            self.current_item_number = self.exam_format.get_possible_item_number(
                    lines[i])
            self._record_line(action)
            self._apply_range(lines[i])
            i += 1
        return span, i

    def _emit_span(self, span_lines):
        """span 关闭：非空则（可选 debug 打印后）拆成单题。"""
        text = '\n'.join(span_lines).strip()
        if not text:
            return
        if self.is_verbose:
            print('=' * 100)
            print(text)
        self._parse_span_into_questions(text)

    # split it back into :
    # event: find question_context end
    # event: attach question_context to question
    # event: attach question_context to question
    # ...
    # clear question_context
    def split_into_items(self, lines, detect_start, expected_start_num, expected_end_num):
        """把若干行切成「编号严格连续」的一条条 item（题目 / 答案共用）。

        FSM：维护下一个期望号 expected（从 expected_start_num 起逐一递增）。某行
        只有在 detect_start(line) == expected（且不超过 expected_end_num）时才算新
        item 起点，并令 expected += 1；否则并入当前 item。这样保证 item 号严格
        1,2,3,… 连续，把正文里题号对不上的编号行（答案解析里引用的 "7."、子问题
        列表、题干内编号等）挡在外面。首个 item 起点之前的行被丢弃。
        expected_end_num 为 None 表示不设上界。返回 [(key, [lines]), ...]。
        """
        items = []  # [(key, [lines])]
        expected = expected_start_num
        for line in lines:
            key = detect_start(line)
            if key == expected and (expected_end_num is None or expected <= expected_end_num):
                items.append((key, [line]))
                expected += 1
            elif items:
                items[-1][1].append(line)
        return items

    def _parse_span_into_questions(self, span_text):
        """span 内分出 passage 和各题（原 _3._split_span_into_questions）。

        一行只有在「匹配 question_line_re 且题号 == next_question_number
        （全局连续）」时才算题目起始——span 内题号对不上的编号列表（plt 的
        Goals 1.–4.、题干里的子问题）留在 passage/题干里。
        """
        lines = span_text.splitlines()
        # 先把 passage 单独抽出来：首题之前的所有行（首题一旦出现，后续行都归题目）
        first_question_idx = next(
            (i for i, line in enumerate(lines)
             if self.exam_format.get_possible_item_number( line) == self.next_item_number),
            len(lines))
        passage = '\n'.join(lines[:first_question_idx]).rstrip()
        span_start_line_index = self.current_span_start_line_index
        if first_question_idx > 0:
            self.current_line_number = span_start_line_index + first_question_idx - 1
            self.current_item_number = self.exam_format.get_possible_item_number(
                    lines[first_question_idx - 1])
            self._record_line('finish_question_context')

        # 再在首题及其后的行上分题：题号从全局连续计数起严格递增（FSM 内判定），
        # 上界开放（一个 span 的题数不预先知道）
        items = self.split_into_items(
            lines[first_question_idx:],
            lambda line: self.exam_format.get_possible_item_number( line),
            expected_start_num=self.next_item_number,
            expected_end_num=(
                self.next_span_first_question - 1
                if self.next_span_first_question > self.next_item_number
                else None
            ),
        )
        for qnum, qlines in items:
            item_line_index = span_start_line_index + next(
                    i for i, line in enumerate(lines)
                    if self.exam_format.get_possible_item_number(line) == qnum
            )
            self.current_line_number = item_line_index
            self.current_item_number = qnum
            self._record_line('attach_question_context')
            self.items.append(
                (qnum, passage, '\n'.join(qlines).strip()))
        if first_question_idx > 0 and items:
            last_qnum = items[-1][0]
            last_item_line_index = span_start_line_index + next(
                    i for i, line in enumerate(lines)
                    if self.exam_format.get_possible_item_number(line) == last_qnum
            )
            self.current_line_number = last_item_line_index
            self.current_item_number = last_qnum
            self._record_line('clear_question_context')
        self.next_item_number += len(items)  # 跨 span 推进全局题号
        self.next_span_first_question = max(
            self.next_span_first_question, self.next_item_number)

    def _parse_till_context_item_finish(self, lines):
        """passage-question span：从 trigger 行起，吃完整个 span（passage + 其各题）。"""
        self.has_mainbody_started = True
        i = self.current_line_number
        self.current_span_start_line_index = i
        span, next_i = self._consume(lines, i, stop_at_question_start=False)
        self._emit_span(span)
        # _emit_span 会反复改动 self.current_line_number，这里复位到 span 之后的待处理行
        self.current_line_number = next_i

    def parse_till_item_finish(self, lines):
        """无 passage 的独立题：从题目行起，吃完这一道题。"""
        if self.has_mainbody_started:
            print(f'WARNING: question {self.next_span_first_question} appeared '
                  f'without a preceding trigger line — if it has a '
                  f'passage, the passage stayed in the previous span')
        self.has_mainbody_started = True
        self.next_span_first_question += 1
        # 独立题内不会出现 range 行：praxis 的 range 行就是 trigger（会被
        # _is_span_start 先终止本 span）；plt 的 "Directions:" 行必跟在
        # Case History/Discrete trigger 之后，不会落在无-trigger 的独立题里。
        # 因此 _consume 沿途的 _apply_range 必是 no-op，不会推进首题号——断言之。
        before = self.next_span_first_question
        i = self.current_line_number
        self.current_span_start_line_index = i
        span, next_i = self._consume(lines, i)
        assert self.next_span_first_question == before, (
            f'independent question span unexpectedly contained a range line: {span!r}')
        self._emit_span(span)
        # 同上：_emit_span 改动游标后复位到下一待处理行
        self.current_line_number = next_i

    def parse(self, md_text):
        lines = md_text.splitlines()
        self.lines = lines
        self.items = []
        self.line_trace = []
        self.next_item_number = 1
        self.next_itemspan_first_itemnumber = 1
        self.next_span_first_question = 1
        self.has_mainbody_started = False
        # 用实例属性 self.current_line_number 作为唯一的行游标（与父类 parse 一致），
        # 各 helper 返回的下一个下标赋回它即可。
        self.current_line_number = 0
        while self.current_line_number < len(lines):
            line = lines[self.current_line_number]
            if self.exam_format.is_question_context_start_line(line):
                # passage-question span 起点；helper 内部推进 self.current_line_number
                self._parse_till_context_item_finish(lines)
            elif self.exam_format.get_possible_item_number( line) == self.next_span_first_question:
                # 无 passage 的独立题起点；helper 内部推进 self.current_line_number
                self.parse_till_item_finish(lines)
            else:
                # 既非 trigger 也非独立题起点——只可能是首个 span 之前的杂行。
                # mainbody 已被 _1 裁剪到首个 span 起点，正常不会走到这里
                # （range 行要么是 trigger=进入 span，要么在 span 内被 _consume 吞掉），
                # 跳过即可。
                self.current_item_number = self.exam_format.get_possible_item_number(line)
                self._record_line('skip')
                self.current_line_number += 1
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
            for qnum, passage, question in questions:
                writer.writerow(asdict(IndividualQuestionRow(
                    question_number=str(qnum),
                    passage=passage,
                    question=question,
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
                    fieldnames=[
                            'line_number',
                            'expected_item_number',
                            'expected_span_first_question',
                            'item_number',
                            'action',
                            'line',
                            'caller_function',
                            'caller_location',
                    ],
                    extrasaction='ignore',
            )
            writer.writeheader()
            writer.writerows(asdict(r) for r in fsm.line_trace)
        print(f'wrote {len(questions)} questions to {output_path}')
        print(f'wrote question FSM trace to {trace_output_path}')

if __name__ == '__main__':
    # 从 fixture 的输入 md 沿 _1_ 的 derive 推出 questions_mainbody.md
    SplitQuestionMainbodyIntoIndividualQuestionsStage().run(
        GetQuestionsMainbodyStage().derive_output_path(mineruparsed))
