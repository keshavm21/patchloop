from solution import top_k_words


def test_counts():
    assert top_k_words("b a b c b a", 2) == ["b", "a"]


def test_ties_alphabetical():
    assert top_k_words("pear apple fig", 2) == ["apple", "fig"]


def test_case_folding():
    assert top_k_words("Go go GO stop", 1) == ["go"]
