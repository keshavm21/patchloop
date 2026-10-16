VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(numeral):
    """Convert a valid Roman numeral (1 to 3999), such as "XIV", to an int."""
    total = 0
    for i, ch in enumerate(numeral):
        value = VALUES[ch]
        if i + 1 < len(numeral) and VALUES[numeral[i + 1]] > value:
            total -= value
        else:
            total += value
    return total
