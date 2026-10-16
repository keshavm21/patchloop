from collections import Counter


def top_k_words(text, k):
    """Return the k most frequent words in text, lowercased.

    Words are split on whitespace. Higher counts come first; equal counts are ordered
    alphabetically.
    """
    counts = Counter(text.lower().split())
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranked[:k]]
