"""Lossless cleanup of the repeated/empty columns in extracted SEC tables."""

import re
from itertools import zip_longest


def compact_table(lines: list[str]) -> list[str]:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    columns = list(zip_longest(*rows, fillvalue=""))
    kept = []
    seen = set()
    for index, column in enumerate(columns):
        values = tuple(value for value in column if not re.fullmatch(r":?-+:?", value))
        if any(values) and values not in seen:
            kept.append(index)
            seen.add(values)
    return ["| " + " | ".join(columns[index][row] for index in kept) + " |" for row in range(len(rows))]


def compact_passage(text: str) -> str:
    lines = text.splitlines()
    result = []
    table = []
    for line in [*lines, ""]:
        if line.lstrip().startswith("|"):
            table.append(line)
        else:
            if table:
                result.extend(compact_table(table))
                table = []
            result.append(line)
    return "\n".join(result).strip()
