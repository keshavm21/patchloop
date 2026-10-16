"""Chaos: allocates far beyond the memory cap, touching every page so none stay lazy."""


def second_largest(nums):
    hog = []
    for _ in range(4096):  # 4 GiB in 1 MiB chunks
        hog.append(b"\x01" * (1 << 20))
    return len(hog)
