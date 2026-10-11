"""Fill short caption gaps without moving the next caption's speech start."""
import argparse
import json
import math
from pathlib import Path


def connect(rows, max_gap=0.35):
    if not math.isfinite(max_gap) or max_gap < 0:
        raise ValueError("max_gap must be nonnegative")
    result = [dict(row) for row in rows]
    for i, row in enumerate(result):
        start, end = float(row["start"]), float(row["end"])
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
            raise ValueError(f"invalid caption {i}")
        row["start"], row["end"] = start, end
        if i and start < result[i - 1]["end"]:
            raise ValueError(f"overlapping or unsorted caption {i}")
    for current, following in zip(result, result[1:]):
        gap = following["start"] - current["end"]
        # An explicit boundary prevents filling even a short intentional pause.
        if 0 < gap <= max_gap and not current.get("keep_gap", False):
            current["original_end"] = current["end"]
            current["end"] = following["start"]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--max-gap", type=float, default=0.35)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sample = [{"start": 0, "end": 1}, {"start": 1.2, "end": 2},
                  {"start": 3, "end": 4, "keep_gap": True},
                  {"start": 4.2, "end": 5}]
        output = connect(sample)
        assert output[0]["end"] == 1.2
        assert output[1]["end"] == 2
        assert output[2]["end"] == 4
        assert [r["start"] for r in output] == [r["start"] for r in sample]
        assert sample[0]["end"] == 1
        for bad in ([{"start": 1, "end": 1}],
                    [{"start": 0, "end": 2}, {"start": 1, "end": 3}]):
            try:
                connect(bad)
            except ValueError:
                continue
            raise AssertionError("invalid timeline accepted")
        print("caption continuity tests passed")
        return
    if not args.input or not args.output:
        parser.error("input and output are required")
    source, target = Path(args.input), Path(args.output)
    if source.resolve() == target.resolve() or target.exists():
        parser.error("output must be a new file")
    rows = json.loads(source.read_text(encoding="utf-8-sig"))
    result = connect(rows, args.max_gap)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
