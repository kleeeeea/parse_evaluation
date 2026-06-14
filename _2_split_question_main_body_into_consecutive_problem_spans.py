import csv
from dataclasses import asdict

from _1_get_questions_mainbody import GetQuestionsMainbodyStage
from dataclass_ import QuestionSpanRow
from dataclass_ import columns
from exam_formats import ExamFormat
from exam_formats import PRAXIS_READING
from exam_formats import question_number_match
from stage import Stage
from tests.fixture._constants import mineruparsed

questionspan_output_csv_basename = 'question_spans.csv'
output_csv_columns = columns(QuestionSpanRow)
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


def _split_markdown_into_spans(md_text, exam_format: ExamFormat = PRAXIS_READING, debug=True):
    """FSM over lines; a span starts only at a span_trigger_re line.

    span_trigger_re 是 span 唯一的起点（praxis: "Use the following
    passage…" trigger 行；plt: "## Case History N" / "## Discrete
    Multiple-Choice Questions" 节标题）。之后的所有行——passage/案例、
    题目、选项、折行文本——都留在当前 span 里直到下一个 trigger，
    不需要 pending 缓冲。

    `next_question_number` directly indicates the first question of the NEXT
    span: question_range_re 命中的行（praxis 的 trigger 行本身；plt 的
    Directions 行）声明范围 [a, b]，必须满足 a == next_question_number
    （否则 span 之间漏了题），然后置 next_question_number = b + 1。
    范围内的题目行 a..b 不需要逐题计数——它们是普通 span 内容。
    因此题号 == next_question_number 的题目行只可能意味着上一个 span
    结束：关闭它并从题目行开新 span。（正常情况下不会触发——下一个
    trigger 会先到并把计数推过本组题号。只对无 trigger 的独立题触发：
    每题自成一个 span；如果是 trigger 行解析漏了，passage 文本会留在
    上一个 span 里——打 WARNING。）

    The input is the pre-trimmed questions mainbody (output of
    get_questions_mainbody.py)：无前言、无答案区。
    """
    spans = []
    current = None  # lines of the span being built
    next_question_number = 1  # first question number of the next span

    def close_current():
        nonlocal current
        if current is not None:
            text = '\n'.join(current).strip()
            if text:
                spans.append(text)
                if debug:
                    print(separator)
                    print(text)
        current = None

    separator = '=' * 100
    for line in md_text.splitlines():
        if exam_format.span_trigger_re.match(line):
            # The single place a new span starts.
            close_current()
            current = [line]
        elif question_number_match(exam_format, line) == next_question_number:
            # The end of the previous span: close it and start a new span at
            # the question line itself (trigger-less question).
            if current is not None:
                print(f'WARNING: question {next_question_number} appeared '
                      f'without a preceding trigger line — if it has a '
                      f'passage, the passage stayed in the previous span')
            close_current()
            current = [line]
            next_question_number += 1
        elif current is not None:
            current.append(line)
        # 范围声明行可能是 trigger 行本身（praxis），也可能是 span 内的
        # Directions 行（plt），所以独立于上面的分支检查。
        range_match = exam_format.question_range_re.search(line)
        if range_match:
            first_q = int(range_match.group(1))
            last_q = int(range_match.group(2) or range_match.group(1))
            if first_q != next_question_number:
                print(f'WARNING: range line declares questions {first_q}…{last_q} '
                      f'but the next span should start at question {next_question_number}')
                raise ValueError(line)
            # next_question_number directly indicates the next span start
            next_question_number = last_q + 1
    close_current()
    print(f'FSM saw questions 1..{next_question_number - 1} in {len(spans)} spans')
    return spans


class SplitQuestionMainbodyIntoSpansStage(Stage):
    # …/{dataset}/outputs/questions_mainbody.md -> …/{dataset}/outputs/question_spans.csv
    output_basename = questionspan_output_csv_basename

    def _produce(self, output_path, current_questions_mainbody_md):
        with open(current_questions_mainbody_md) as f:
            md_text = f.read()
        spans = _split_markdown_into_spans(md_text, self.exam_format)
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=output_csv_columns)
            writer.writeheader()
            for span_text in spans:
                writer.writerow(asdict(QuestionSpanRow(spans=span_text)))
        print(f'wrote {len(spans)} spans to {output_path}')

if __name__ == '__main__':
    # 从 fixture 的输入 md 沿 _1_ 的 derive 推出 questions_mainbody.md
    SplitQuestionMainbodyIntoSpansStage().run(
        GetQuestionsMainbodyStage().derive_output_path(mineruparsed))
