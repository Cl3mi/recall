"""Rerankers: score each fused candidate against the query, precision where fusion gave recall.

A reranker reads one query and the candidates' texts and returns one score per candidate, higher
is more relevant. The real adapters are GPU only (operator, 2026-11-13) and load pinned weights
offline, like E5Embedder. OverlapReranker is a deterministic stand-in, so retrieval and the eval
are testable with no torch, no GPU and no download.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from typing import Protocol

QUERY_CAP = 128  # query tokens a pair keeps; a title or head query never reaches it
PAIR_BUDGET = 512  # content tokens per pair, the same for every model (plan amendment 2)
_WORD = re.compile(r"[a-z0-9äöüß_]+")

Candidate = tuple[str, str | None]  # problem text, solution text or None


class Reranker(Protocol):
    identity: str
    device: str

    def score(self, query: str, candidates: list[Candidate]) -> list[float]: ...


class OverlapReranker:
    """The share of the query's distinct words that occur in the candidate.

    Not a model and not pretending to be one: enough to give the rerank path a real ordering in
    tests. Its identity begins with `overlap:` so a report made with it cannot pass for a model's.
    """

    identity = "overlap:words"
    device = "cpu"

    def score(self, query: str, candidates: list[Candidate]) -> list[float]:
        words = set(_WORD.findall(query.casefold()))
        scores = []
        for problem, solution in candidates:
            found = set(_WORD.findall(f"{problem} {solution or ''}".casefold()))
            scores.append(len(words & found) / len(words) if words else 0.0)
        return scores


def fit(
    query: Sequence[int],
    problem: Sequence[int],
    solution: Sequence[int] | None = None,
    *,
    sep: Sequence[int] = (),
    total: int = PAIR_BUDGET,
    query_cap: int = QUERY_CAP,
) -> tuple[list[int], list[int]]:
    """Cut token ids to one pair's budget: the query to query_cap, the candidate to the rest.

    With a solution, problem and solution get half of the candidate's share each (the separator
    counts against it) and a side that needs less leaves the rest to the other, so a long
    description cannot push the fix out of the window. Returns (query ids, candidate ids)."""
    q = list(query[:query_cap])
    room = total - len(q)
    if solution is None:
        return q, list(problem[:room])
    room -= len(sep)
    take_problem = min(len(problem), max(room // 2, room - len(solution)))
    take_solution = min(len(solution), room - take_problem)
    return q, list(problem[:take_problem]) + list(sep) + list(solution[:take_solution])


# Pinned like E5_REVISION: a model name without a revision is a claim about whatever the hub
# served that day. Both Apache-2.0 (master design §12.5).
BGE_MODEL = "BAAI/bge-reranker-v2-m3"
BGE_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
QWEN_MODEL = "Qwen/Qwen3-Reranker-4B"
QWEN_REVISION = "22e683669bc0f0bd69640a1354a6d0aebcfeede5"
BATCH = 16
SOLUTION_SEP = "\nLösung: "
# One fixed instruction, written into the spec before the run and not tuned (operator,
# 2026-11-13). Only the Qwen model reads it; bge has no instruction slot.
INSTRUCTION = (
    "Given a vehicle service ticket, judge whether the candidate ticket describes the same fault "
    "with the same cause, so its fix applies."
)
# The frame from the Qwen3-Reranker model card: the answer is read off the "yes"/"no" logits.
QWEN_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
QWEN_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def _gpu(torch) -> str:
    if not torch.cuda.is_available():
        raise RuntimeError("the reranker is GPU only: no CUDA device is visible")
    return "cuda"


def _ids(tokenizer, text: str) -> list[int]:
    return tokenizer.encode(text, add_special_tokens=False)


def fitted(tokenizer, query: str, candidate: Candidate) -> tuple[list[int], list[int]]:
    """Query and candidate as token ids within the pair budget (see fit)."""
    problem, solution = candidate
    return fit(
        _ids(tokenizer, query),
        _ids(tokenizer, problem),
        None if solution is None else _ids(tokenizer, solution),
        sep=_ids(tokenizer, SOLUTION_SEP),
    )


def qwen_input_ids(tokenizer, query: str, candidate: Candidate) -> list[int]:
    """One Qwen3-Reranker input: the card's frame around instruction, query and document."""
    q, doc = fitted(tokenizer, query, candidate)
    head = _ids(tokenizer, f"{QWEN_PREFIX}<Instruct>: {INSTRUCTION}\n<Query>: ")
    return head + q + _ids(tokenizer, "\n<Document>: ") + doc + _ids(tokenizer, QWEN_SUFFIX)


def bge_input_ids(tokenizer, query: str, candidate: Candidate) -> list[int]:
    """One bge-reranker pair in the XLM-RoBERTa layout, `<s> query </s></s> document </s>`.

    Built by hand from the tokenizer's special-token ids: transformers 5 no longer offers
    prepare_for_model, and the budget (see fit) counts content tokens only."""
    q, doc = fitted(tokenizer, query, candidate)
    sep = [tokenizer.sep_token_id]
    return [tokenizer.cls_token_id] + q + sep + sep + doc + sep


class BgeReranker:
    """`BAAI/bge-reranker-v2-m3`, a cross-encoder: the raw relevance logit is the score."""

    def __init__(self, model: str = BGE_MODEL, revision: str = BGE_REVISION) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.device = _gpu(torch)
        self._tokenizer = AutoTokenizer.from_pretrained(
            model, revision=revision, local_files_only=True
        )
        self._model = (
            AutoModelForSequenceClassification.from_pretrained(
                model, revision=revision, local_files_only=True, dtype=torch.float16
            )
            .eval()
            .to(self.device)
        )
        self.identity = f"bge:{model}@{revision}"

    def score(self, query: str, candidates: list[Candidate]) -> list[float]:
        torch = self._torch
        scores: list[float] = []
        for start in range(0, len(candidates), BATCH):
            pairs = [
                {"input_ids": bge_input_ids(self._tokenizer, query, c)}
                for c in candidates[start : start + BATCH]
            ]
            batch = self._tokenizer.pad(pairs, return_tensors="pt")
            batch = {name: tensor.to(self.device) for name, tensor in batch.items()}
            with torch.no_grad():
                logits = self._model(**batch).logits.view(-1).float()
            scores.extend(logits.cpu().tolist())
        return scores


class Qwen3Reranker:
    """`Qwen/Qwen3-Reranker-4B`: P("yes") at the last position of the card's frame is the score."""

    def __init__(self, model: str = QWEN_MODEL, revision: str = QWEN_REVISION) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self.device = _gpu(torch)
        self._tokenizer = AutoTokenizer.from_pretrained(
            model, revision=revision, local_files_only=True, padding_side="left"
        )
        self._model = (
            AutoModelForCausalLM.from_pretrained(
                model, revision=revision, local_files_only=True, dtype=torch.bfloat16
            )
            .eval()
            .to(self.device)
        )
        self._yes = self._tokenizer.convert_tokens_to_ids("yes")
        self._no = self._tokenizer.convert_tokens_to_ids("no")
        self.identity = f"qwen3:{model}@{revision}"

    def score(self, query: str, candidates: list[Candidate]) -> list[float]:
        torch = self._torch
        scores: list[float] = []
        for start in range(0, len(candidates), BATCH):
            inputs = [
                {"input_ids": qwen_input_ids(self._tokenizer, query, c)}
                for c in candidates[start : start + BATCH]
            ]
            batch = self._tokenizer.pad(inputs, return_tensors="pt")
            batch = {name: tensor.to(self.device) for name, tensor in batch.items()}
            with torch.no_grad():
                last = self._model(**batch).logits[:, -1, :]
            pair = torch.stack([last[:, self._no], last[:, self._yes]], dim=1).float()
            scores.extend(torch.log_softmax(pair, dim=1)[:, 1].exp().cpu().tolist())
        return scores


RERANKERS = {"bge": BgeReranker, "qwen3_4b": Qwen3Reranker}

# Synthetic smoke pair: invented text, safe to print.
SMOKE_QUERY = "Hydraulikpumpe baut keinen Druck auf, Lenkung geht schwer"
SMOKE_SAME = ("Lenkung schwergängig, Hydraulikpumpe ohne Druck", "Pumpe getauscht, Druck i.O.")
SMOKE_OTHER = ("Klimaanlage kühlt nicht", "Kältemittel nachgefüllt")


def main(argv: list[str] | None = None) -> int:
    """python -m recall.rerank smoke --model bge|qwen3_4b

    Loads the model offline on the GPU and checks that a same-fault pair outscores an unrelated
    one, with and without the solution. Exit 0 when it does."""
    parser = argparse.ArgumentParser(prog="recall.rerank")
    parser.add_argument("command", choices=("smoke",))
    parser.add_argument("--model", choices=sorted(RERANKERS), required=True)
    args = parser.parse_args(argv)
    reranker = RERANKERS[args.model]()
    with_solution = reranker.score(SMOKE_QUERY, [SMOKE_SAME, SMOKE_OTHER])
    problem_only = reranker.score(SMOKE_QUERY, [(SMOKE_SAME[0], None), (SMOKE_OTHER[0], None)])
    ok = with_solution[0] > with_solution[1] and problem_only[0] > problem_only[1]
    report = {
        "identity": reranker.identity,
        "device": reranker.device,
        "with_solution": with_solution,
        "problem_only": problem_only,
        "ok": ok,
    }
    print(json.dumps(report))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
