import re

import pandas as pd

llm_response_file = '/Users/l/klee_code/git_repos/parse_evaluation/outputs_batch_infer_Qwen3-32B/prompts.csv'
# get the judge score


def gold_letter(answer: str) -> str | None:
    # gold answers look like "1. d. <explanation>" — the choice letter follows the number.
    m = re.match(r"\s*\d+\.\s*([a-eA-E])\b", str(answer))
    return m.group(1).upper() if m else None


def pred_letter(llm_response: str) -> str | None:
    # the model emits its reasoning inside <think>...</think>; the choice letter is the
    # first token of the post-think text. Responses whose reasoning was truncated have no
    # closing tag and therefore no extractable answer.
    text = str(llm_response)
    if "</think>" not in text:
        return None
    post = text.split("</think>")[-1].strip()
    m = re.match(r"([a-eA-E])\b", post)
    return m.group(1).upper() if m else None


df = pd.read_csv(llm_response_file)
df["gold"] = df["answer"].map(gold_letter)
df["pred"] = df["llm_response"].map(pred_letter)
df["correct"] = df["gold"] == df["pred"]

scored_path = llm_response_file.replace(".csv", "_scored.csv")
df.to_csv(scored_path, index=False)

n = len(df)
n_answered = int(df["pred"].notna().sum())
n_correct = int(df["correct"].sum())
print(f"saved to {scored_path}")
print(f"accuracy: {n_correct}/{n} = {n_correct / n:.2%}")
print(f"answered: {n_answered}/{n} (accuracy over answered: {n_correct / n_answered:.2%})")
