import csv
import json
import os
import re
from glob import glob



mineruparsed='/Users/l/klee_code/git_repos/parse_evaluation/eaa0dd7f-206c-485e-82db-2b4b355ff0a9_origin copy (dragged).pdf-aafdc8db-4703-4b3b-809a-eadc8088d856/full.md'
questionspan_output_csv = '/Users/l/klee_code/git_repos/parse_evaluation/outputs/question_spans.csv'
output_csv_columns = ['spans']
original_page_screenshot_path_root = '/Users/l/klee_code/git_repos/parse_evaluation/splited'
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

SPAN_TRIGGER_RE = re.compile(r'^\s*Use the following passage', re.IGNORECASE)
# text_level=1 items that should stay inside a span (passage/source sub-labels)
IN_SPAN_TOP_LEVEL_RE = re.compile(r'^\s*(Passage|Source)\s+\d+\s*$', re.IGNORECASE)
# Top-level markdown headers — used as section boundaries unless the header
# text itself is a Passage/Source sub-label.
TOP_LEVEL_HEADER_RE = re.compile(r'^#\s+(.*)$')
# A top-level header that contains this phrase marks the start of the answer
# key — no more problems can appear after it, so we stop walking the file.
END_OF_PROBLEMS_RE = re.compile(r'Answers and Explanations', re.IGNORECASE)


def _split_markdown_into_spans(md_text):
    """Walk the markdown line by line.

    A new span begins at any line matching SPAN_TRIGGER_RE. The current span
    ends either:
      - at the start of the next trigger, or
      - at a top-level markdown header (`# ...`) whose text is NOT a
        Passage/Source sub-label (those stay inside the span).

    Lines before the first trigger (cover page, "Time: 85 Minutes", etc.) are
    discarded.
    """
    spans = []
    current_lines = None
    for line in md_text.splitlines():
        header_match = TOP_LEVEL_HEADER_RE.match(line)
        # The "Answers and Explanations" header marks the end of all problems
        # for this test — and any later top-level section (Writing Test, Math
        # Test, …) is not a problem section either, so we stop entirely.
        # Example line that triggers this:
        #   '# Praxis® Core Academic Skills for Educators: Reading Practice Test 1 Answers and Explanations'
        if header_match and END_OF_PROBLEMS_RE.search(header_match.group(1)):
            if current_lines is not None:
                spans.append('\n'.join(current_lines).strip())
                current_lines = None
            break
        if SPAN_TRIGGER_RE.match(line):
            if current_lines is not None:
                spans.append('\n'.join(current_lines).strip())
            current_lines = [line]
            continue
        if current_lines is None:
            continue
        if header_match and not IN_SPAN_TOP_LEVEL_RE.match(header_match.group(1)):
            # New top-level section — close the current span and stop collecting
            # until the next trigger.
            spans.append('\n'.join(current_lines).strip())
            current_lines = None
            continue
        current_lines.append(line)
    if current_lines is not None:
        spans.append('\n'.join(current_lines).strip())
    return [s for s in spans if s]


def split_mineru_parsed_md_into_consecutive_problem_spans(current_mineruparsed):
    with open(current_mineruparsed) as f:
        md_text = f.read()
    spans = _split_markdown_into_spans(md_text)
    out_dir = os.path.dirname(questionspan_output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(questionspan_output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(output_csv_columns)
        for span_text in spans:
            writer.writerow([span_text])
    print(f'wrote {len(spans)} spans to {questionspan_output_csv}')


if __name__ == '__main__':
    split_mineru_parsed_md_into_consecutive_problem_spans(mineruparsed)
