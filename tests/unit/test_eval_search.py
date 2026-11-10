"""The search evaluation's scoring and its made-up cases, without a database or model."""

import json

from scripts import eval_search

KEYS = {"a": ("message", 1), "b": ("action", 2)}


def test_a_right_answer_in_the_top_five_counts():
    question = {"expect": ["b"]}
    assert eval_search.score(question, [("message", 9), ("action", 2)], KEYS) == {"recall": True, "reciprocal_rank": 0.5}
    ranking = [("message", n) for n in range(10, 16)] + [("action", 2)]
    assert eval_search.score(question, ranking, KEYS) == {"recall": False, "reciprocal_rank": 1 / 7}


def test_questions_with_no_answer_must_come_back_empty():
    assert eval_search.score({"expect": []}, [], KEYS) == {"empty": True}
    assert eval_search.score({"expect": []}, [("message", 1)], KEYS) == {"empty": False}


def test_summary_is_per_type_and_over_all_answerable():
    summary = eval_search.summarize(
        [
            ("exact", {"recall": True, "reciprocal_rank": 1.0}),
            ("same_meaning", {"recall": False, "reciprocal_rank": 0.0}),
            ("nothing", {"empty": True}),
        ]
    )
    assert summary["answerable"] == {"questions": 2, "recall_at_5": 0.5, "mrr": 0.5}
    assert summary["nothing"] == {"questions": 1, "empty_rate": 1}


def test_best_cutoff_keeps_empty_answers_empty():
    def row(cutoff, recall, empty):
        return {"cutoff": cutoff, "hybrid": {"answerable": {"recall_at_5": recall, "mrr": recall}, "nothing": {"empty_rate": empty}}}

    assert eval_search.best_cutoff([row(0.4, 1.0, 0.5), row(0.5, 0.9, 0.95), row(0.6, 0.8, 1.0)]) == 0.5


def test_every_question_points_at_a_real_case():
    cases = json.loads(eval_search.CASES_FILE.read_text())
    keys = [item["key"] for chat in cases["chats"] for item in chat.get("messages", []) + chat.get("actions", [])]
    assert len(keys) == len(set(keys))
    for question in cases["questions"]:
        assert set(question["expect"]) <= set(keys), question["query"]
    types = {question["type"] for question in cases["questions"]}
    assert types == {"same_meaning", "exact", "dates", "actions", "nothing"}
    assert 40 <= len(cases["questions"]) <= 60
