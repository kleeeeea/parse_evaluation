# 把得到第一个span开头之前 的所有逻辑 移动到这里 产生单独的md output
import os
import re

from dataclass_ import Stage
from parse_evaluation.exam_formats import ExamFormat
from tests.fixture._constants import mineruparsed


def slice_mainbody(lines, is_start, is_end, *, default_start):
    """切出文档主体的 [start, end) 行区间。"""
    start = next((i for i, l in enumerate(lines) if is_start(l)), default_start)
    end = next((i for i in range(start, len(lines)) if is_end(lines[i])), len(lines))
    while end > start and (not lines[end - 1].strip()
                           or re.fullmatch(r'\s*\d+\s*', lines[end - 1])):
        end -= 1
    return start, end



def _get_questions_mainbody(md_text, exam_format: ExamFormat):
    """Slice the markdown down to the questions main body.

    起点：第一个 span trigger 行（praxis: "Use the following passage…"；
    plt: "## Case History 1"）或题号为 1 的题目行，二者取更早者——
    封面、限时说明、Directions 等前言全部丢弃。
    终点：mainbody_end_re 命中的标题之前（praxis: "# …Answers and
    Explanations"，答案区及后续 Writing/Math 区段全部丢弃）；
    mainbody_end_re 为 None 表示题目文档没有答案区（题/答分开两份
    PDF），主体直到文件尾。
    """
    lines = md_text.splitlines()
    # 处理第一个题目没有Passage， 直接是 "1.{question}" 的情况：
    # 起点取「第一个 trigger 行」和「题号为 1 的题目行」中更早出现者
    def _is_mainbody_start(l):
        if exam_format.is_question_context_start_line(l):
            return True
        return exam_format.get_possible_item_number(l) == 1

    start, end = slice_mainbody(lines, _is_mainbody_start, exam_format.is_question_mainbody_end_line, default_start=0)
    return '\n'.join(lines[start:end]).strip() + '\n'


class GetQuestionsMainbodyStage(Stage):
    # …/{dataset}/{mineru任务目录}/full.md -> …/{dataset}/{mineru任务目录}/questions_mainbody.md
    # output to the same root（输入所在目录，不再依赖全局输出根目录）
    output_basename = 'questions_mainbody.md'

    def _produce(self, output_path, input_document):
        with open(input_document) as f:
            md_text = f.read()
        mainbody = _get_questions_mainbody(md_text, self.exam_format)
        with open(output_path, 'w') as f:
            f.write(mainbody)
        print(f'wrote {len(mainbody.splitlines())} lines to {output_path}')


if __name__ == '__main__':
    GetQuestionsMainbodyStage().run(mineruparsed)
