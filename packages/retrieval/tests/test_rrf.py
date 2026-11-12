import pytest

from eagleeye_retrieval.rrf import fuse


def test_single_ranking_preserves_order() -> None:
    assert [i for i, _ in fuse([["a", "b", "c"]])] == ["a", "b", "c"]


def test_item_in_both_rankings_wins() -> None:
    result = [i for i, _ in fuse([["a", "b"], ["c", "b"]])]
    assert result[0] == "b"


def test_weights_shift_preference() -> None:
    heavy_first = fuse([["a"], ["b"]], weights=[0.7, 0.3])
    assert heavy_first[0][0] == "a"
    heavy_second = fuse([["a"], ["b"]], weights=[0.3, 0.7])
    assert heavy_second[0][0] == "b"


def test_ties_keep_first_seen_order() -> None:
    assert [i for i, _ in fuse([["x"], ["y"]])] == ["x", "y"]


def test_empty_inputs() -> None:
    assert fuse([]) == []
    assert fuse([[], []]) == []


def test_duplicate_in_one_ranking_counted_once() -> None:
    once = dict(fuse([["a"]]))["a"]
    dup = dict(fuse([["a", "a"]]))["a"]
    assert once == pytest.approx(dup)


def test_weight_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        fuse([["a"]], weights=[1.0, 2.0])
