from solution import top_k_words


def test_counts():
    assert top_k_words("b a b c b a", 2) == ["b", "a"]


def test_ties_alphabetical():
    assert top_k_words("pear apple fig", 2) == ["apple", "fig"]


def test_case_folding():
    assert top_k_words("Go go GO stop", 1) == ["go"]


def test_k_larger():
    assert top_k_words("x y", 5) == ["x", "y"]


def test_empty():
    assert top_k_words("", 3) == []


def test_tie_after_leader():
    assert top_k_words("a c b c", 3) == ["c", "a", "b"]


def test_k_zero():
    assert top_k_words("a a b", 0) == []
