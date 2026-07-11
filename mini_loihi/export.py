from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return to_plain_data(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain_data(item) for item in value]
    return value


def dumps_json(value: Any) -> str:
    return json.dumps(to_plain_data(value), indent=2, sort_keys=True)


def write_json(value: Any, path: str | Path) -> None:
    Path(path).write_text(dumps_json(value) + "\n", encoding="utf-8")


def write_csv_rows(rows: list[dict[str, Any]], path: str | Path) -> None:
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def benchmark_rows(results: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        data = to_plain_data(result)
        rows.append(
            {
                key: value
                for key, value in data.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
        )
    return rows


def learning_curve_rows(accuracy_history: tuple[float, ...], reward_history: tuple[int, ...]) -> list[dict[str, Any]]:
    return [
        {
            "trial": index,
            "accuracy": accuracy,
            "reward": reward_history[index] if index < len(reward_history) else "",
        }
        for index, accuracy in enumerate(accuracy_history)
    ]
