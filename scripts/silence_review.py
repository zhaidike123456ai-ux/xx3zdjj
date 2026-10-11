"""Parse FFmpeg silence measurements into legal media coordinates.

AAC decoding may add PCM padding. These measurements are preserved in an audit,
but only nonempty intervals inside the container timeline are review candidates.
Clamping is a coordinate conversion, never evidence that speech was cut off.
"""
from __future__ import annotations

import math
import re


_EVENT = re.compile(r"\bsilence_(start|end|duration):\s*([^\s|]+)")


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _duration(value, name):
    number = _finite_number(value)
    if number is None or number < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return number


def decoded_duration_diagnostic(media_duration_seconds, decoded_duration_seconds, *,
                                absolute_threshold_seconds=0.1,
                                relative_threshold=0.001,
                                maximum_threshold_seconds=0.5):
    """Compare the actual decoded WAV duration with the container duration.

    Allowed difference is max(100 ms, 0.1% of media duration), capped at 500 ms.
    This is an explicit diagnostic policy, not a codec-padding guarantee. Larger
    differences require technical review; no claim of swallowed speech is made.
    Do not substitute the last ``silence_end`` for actual decoded WAV duration.
    """
    media = _duration(media_duration_seconds, "media duration")
    decoded = _duration(decoded_duration_seconds, "decoded duration")
    absolute = _duration(absolute_threshold_seconds, "absolute threshold")
    relative = _duration(relative_threshold, "relative threshold")
    maximum = _duration(maximum_threshold_seconds, "maximum threshold")
    if maximum < absolute:
        raise ValueError("maximum threshold must be at least the absolute threshold")
    threshold = min(maximum, max(absolute, media * relative))
    difference = decoded - media
    requires_review = abs(difference) > threshold + 1e-9
    return {
        "code": "decoded_media_duration_difference",
        "status": "review_required" if requires_review else "within_tolerance",
        "review_required": requires_review,
        "severity": "warning" if requires_review else "info",
        "media_duration_seconds": media,
        "decoded_duration_seconds": decoded,
        "difference_seconds": difference,
        "absolute_difference_seconds": abs(difference),
        "threshold_seconds": threshold,
        "threshold_policy": {
            "absolute_seconds": absolute, "relative_fraction": relative,
            "maximum_seconds": maximum,
        },
        "measurement": "actual decoded PCM duration compared with media duration",
        "reason": ("duration difference exceeds the technical-review threshold; "
                   "check stream timing and extraction; this is not evidence of swallowed speech"
                   if requires_review else
                   "duration difference is within the configured technical tolerance; "
                   "semantic speech quality is not assessed"),
    }


def parse_silence_measurements(stderr: str, duration: float) -> dict:
    """Return bounded intervals plus an audit of every measurement and anomaly.

    Events are paired in log order, rather than matching separate start/end
    lists. Malformed, unmatched, or reversed measurements are diagnosed and
    preserved, not shifted onto a different interval. An unterminated final
    start is closed at media duration, as FFmpeg may omit its end marker.
    """
    media_duration = _duration(duration, "media duration")
    if not isinstance(stderr, str):
        raise TypeError("FFmpeg log must be text")
    measurements = []
    diagnostics = []
    pending = None
    previous_end = None

    def diagnose(code, measurement, reason, *, review=True):
        diagnostics.append({
            "code": code, "measurement_index": measurement["index"],
            "severity": "warning" if review else "info",
            "review_required": review, "reason": reason,
        })

    def new_measurement(raw_start=None, raw_end=None, *, line=None):
        item = {
            "index": len(measurements), "line": line,
            "raw_start_text": raw_start, "raw_end_text": raw_end,
            "raw_duration_text": None,
            "raw_start": _finite_number(raw_start),
            "raw_end": _finite_number(raw_end),
            "raw_reported_duration": None,
            "end_source": "ffmpeg" if raw_end is not None else None,
        }
        measurements.append(item)
        return item

    for line_number, line in enumerate(stderr.splitlines(), 1):
        for event, raw in _EVENT.findall(line):
            if event == "start":
                previous_end = None
                if pending is not None:
                    pending["drop_reason"] = "missing_end_before_next_start"
                    diagnose("unpaired_start", pending,
                             "another silence_start arrived before an end; interval not inferred")
                pending = new_measurement(raw_start=raw, line=line_number)
            elif event == "end":
                if pending is None:
                    previous_end = new_measurement(raw_end=raw, line=line_number)
                    previous_end["drop_reason"] = "missing_start"
                    diagnose("unpaired_end", previous_end,
                             "silence_end has no matching start; interval not inferred")
                else:
                    pending.update(raw_end_text=raw, raw_end=_finite_number(raw),
                                   end_source="ffmpeg")
                    previous_end = pending
                    pending = None
            elif previous_end is not None:
                previous_end["raw_duration_text"] = raw
                previous_end["raw_reported_duration"] = _finite_number(raw)
            else:
                # Keep orphan duration text in the audit without fabricating
                # start/end coordinates or attaching it to a later interval.
                item = new_measurement(line=line_number)
                item.update(raw_duration_text=raw, raw_reported_duration=_finite_number(raw),
                            drop_reason="missing_start_and_end")
                diagnose("unpaired_duration", item,
                         "silence_duration has no preceding end measurement")

    if pending is not None:
        pending.update(inferred_end=media_duration, end_source="media_duration_fallback")

    intervals = []
    for item in measurements:
        start, end = item["raw_start"], item.get("inferred_end", item["raw_end"])
        item.update(retained=False, start=None, end=None, duration=0.0,
                    start_adjustment_seconds=None, end_adjustment_seconds=None,
                    clipped_duration_seconds=None)
        if start is None or end is None:
            if "drop_reason" not in item:
                item["drop_reason"] = "invalid_or_nonfinite_time"
                diagnose("invalid_silence_time", item,
                         "silence bounds are missing, malformed, or nonfinite")
            continue
        if not math.isfinite(end-start):
            item["drop_reason"] = "nonfinite_measurement_span"
            diagnose("invalid_silence_span", item,
                     "finite bounds overflow when subtracted; interval not emitted")
            continue
        item["raw_span_duration"] = end - start if item["end_source"] == "ffmpeg" else None
        reported = item["raw_reported_duration"]
        if item["raw_duration_text"] is not None:
            if reported is None or reported < 0:
                diagnose("invalid_reported_silence_duration", item,
                         "reported duration is invalid; valid start/end bounds are retained")
            elif abs(reported - (end - start)) > 1e-5:
                diagnose("inconsistent_reported_silence_duration", item,
                         "reported duration differs from end minus start; bounds define the interval")
        if "drop_reason" in item:
            continue
        if end < start and item["end_source"] != "media_duration_fallback":
            item["drop_reason"] = "reversed_measurement"
            diagnose("reversed_silence_bounds", item,
                     "silence end precedes start; no interval emitted")
            continue
        bounded_start = max(0.0, min(start, media_duration))
        bounded_end = max(0.0, min(end, media_duration))
        bounded_duration = bounded_end - bounded_start
        item.update(start=bounded_start, end=bounded_end, duration=bounded_duration,
                    start_adjustment_seconds=bounded_start-start,
                    end_adjustment_seconds=bounded_end-end,
                    clipped_duration_seconds=max(0.0,end-start)-bounded_duration)
        if start != bounded_start or end != bounded_end:
            diagnose("silence_bounds_clamped_to_media", item,
                     "measurement preserved in audit; review coordinates clipped to media timeline",
                     review=False)
        if bounded_end <= bounded_start:
            item["drop_reason"] = "empty_after_media_clamp" if end > start else "zero_duration"
            continue
        item["retained"] = True
        intervals.append({"start": bounded_start, "end": bounded_end,
                          "duration": bounded_duration})

    return {"schema_version": 1, "media_duration_seconds": media_duration,
            "intervals": intervals, "measurements": measurements,
            "diagnostics": diagnostics,
            "review_required": any(x["review_required"] for x in diagnostics)}


def parse_silence(stderr: str, duration: float) -> list[dict]:
    """Compatibility entry point: legal nonempty start/end/duration rows only."""
    return parse_silence_measurements(stderr, duration)["intervals"]
