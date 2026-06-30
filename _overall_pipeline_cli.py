import argparse

from exam_formats import EXAM_FORMATS
from tests.fixture._constants import mineruparsed



def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Parse evaluation question and answer markdown files.',
    )
    parser.add_argument(
        'question_input_document',
        nargs='?',
        help='MinerU parsed question markdown, usually full.md.',
    )
    parser.add_argument(
        'answer_input_document',
        nargs='?',
        help='MinerU parsed answer markdown, usually full.md.',
    )
    from parse_evaluation.exam_formats import EXAM_FORMAT_BY_NAME
    parser.add_argument(
        '--exam-format',
        choices=sorted(EXAM_FORMAT_BY_NAME),
        help='Override exam format detection.',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Recreate outputs even when they already exist.',
    )
    args = parser.parse_args(argv)
    if bool(args.question_input_document) != bool(args.answer_input_document):
        parser.error(
            'question_input_document and answer_input_document must be provided together'
        )
    return args


def main(argv=None):
    args = parse_args(argv)
    question_input_document = args.question_input_document or mineruparsed
    answer_input_document = args.answer_input_document or mineruparsed
    from parse_evaluation.exam_formats import EXAM_FORMAT_BY_NAME
    exam_format = (
        EXAM_FORMAT_BY_NAME[args.exam_format] if args.exam_format else None
    )
    # 每步返回输出路径并作为下一步的输入；输出已存在时各步自动跳过（幂等）
    # 不传 exam_format —— 由题目文档内容自动推断
    from parse_evaluation._overall_pipeline import run_parse_evaluation_pipeline
    run_parse_evaluation_pipeline(
        question_input_document,
        answer_input_document,
        exam_format=exam_format,
        skip_if_output_exists=not args.force,
    )



if __name__ == '__main__':
    main()
