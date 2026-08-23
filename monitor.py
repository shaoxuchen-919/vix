#!/usr/bin/env python3
"""Monitor official Cboe VIX closes and send upward-crossing alerts to WeChat."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable


VIX_CSV_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
THRESHOLDS = (20.0, 25.0, 30.0, 40.0)
DEFAULT_STATE_FILE = Path(__file__).with_name("state.json")
USER_AGENT = "vix-wechat-monitor/1.0 (+GitHub Actions)"


@dataclass(frozen=True)
class VixClose:
    trading_date: date
    close: float


@dataclass(frozen=True)
class Crossing:
    trading_date: date
    thresholds: tuple[float, ...]
    close_two_days_ago: float
    close_previous_day: float
    close_current_day: float


def fetch_vix_history(url: str = VIX_CSV_URL) -> list[VixClose]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8-sig")

    rows: list[VixClose] = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append(
            VixClose(
                trading_date=datetime.strptime(row["DATE"].strip(), "%m/%d/%Y").date(),
                close=float(row["CLOSE"]),
            )
        )
    rows.sort(key=lambda item: item.trading_date)
    if len(rows) < 3:
        raise RuntimeError("Cboe VIX history returned fewer than three rows")
    return rows


def detect_crossings(
    closes: Iterable[VixClose],
    after_date: date | None,
    thresholds: tuple[float, ...] = THRESHOLDS,
) -> list[Crossing]:
    """Detect independent upward crossings using the agreed two-day confirmation.

    A level is crossed when the two preceding closes are at or below the level
    and the current close is strictly above it.
    """

    rows = sorted(closes, key=lambda item: item.trading_date)
    crossings: list[Crossing] = []
    for index in range(2, len(rows)):
        current = rows[index]
        if after_date is not None and current.trading_date <= after_date:
            continue
        previous = rows[index - 1]
        two_days_ago = rows[index - 2]
        crossed = tuple(
            threshold
            for threshold in thresholds
            if two_days_ago.close <= threshold
            and previous.close <= threshold
            and current.close > threshold
        )
        if crossed:
            crossings.append(
                Crossing(
                    trading_date=current.trading_date,
                    thresholds=crossed,
                    close_two_days_ago=two_days_ago.close,
                    close_previous_day=previous.close,
                    close_current_day=current.close,
                )
            )
    return crossings


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"last_checked_date": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read state file {path}: {exc}") from exc


def save_state(path: Path, latest: VixClose, crossings: list[Crossing]) -> None:
    state = {
        "last_checked_date": latest.trading_date.isoformat(),
        "last_vix_close": latest.close,
        "last_crossing_dates": [item.trading_date.isoformat() for item in crossings],
        "updated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def build_message(crossings: list[Crossing]) -> tuple[str, str]:
    latest = crossings[-1]
    all_levels = sorted({level for crossing in crossings for level in crossing.thresholds})
    level_text = "、".join(f"{level:g}" for level in all_levels)
    title = f"VIX上穿提醒：{level_text}"

    lines = [
        "## VIX上穿提醒",
        "",
        "程序检测到以下独立上穿信号：",
        "",
    ]
    for crossing in crossings:
        levels = "、".join(f"{level:g}" for level in crossing.thresholds)
        lines.extend(
            [
                f"- **美国交易日：{crossing.trading_date.isoformat()}**",
                f"  - 上穿档位：{levels}",
                (
                    "  - 最近三个收盘："
                    f"{crossing.close_two_days_ago:.2f} → "
                    f"{crossing.close_previous_day:.2f} → "
                    f"**{crossing.close_current_day:.2f}**"
                ),
            ]
        )
    lines.extend(
        [
            "",
            f"最新VIX收盘：**{latest.close_current_day:.2f}**",
            "",
            "这是监控提醒，不构成投资建议。请同时检查ETF溢价、资金安排和市场状态。",
        ]
    )
    return title, "\n".join(lines)


def send_serverchan(sendkey: str, title: str, description: str) -> None:
    if not sendkey.startswith("SCT"):
        raise RuntimeError("SERVERCHAN_SENDKEY should be a ServerChan Turbo key beginning with SCT")
    endpoint = f"https://sctapi.ftqq.com/{urllib.parse.quote(sendkey, safe='')}.send"
    payload = urllib.parse.urlencode({"title": title, "desp": description}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"ServerChan returned HTTP {exc.code}: {body}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach ServerChan: {exc.reason}") from None
    if result.get("code") != 0:
        raise RuntimeError(f"ServerChan rejected the notification: {result}")


def parse_state_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RuntimeError("last_checked_date in state.json must be a string or null")
    return date.fromisoformat(value)


def run_monitor(state_path: Path, dry_run: bool = False) -> int:
    closes = fetch_vix_history()
    latest = closes[-1]
    state = load_state(state_path)
    last_checked = parse_state_date(state.get("last_checked_date"))

    if last_checked is None:
        print(
            f"Initialising at {latest.trading_date.isoformat()} "
            f"(VIX close {latest.close:.2f}); no historical alert will be sent."
        )
        if not dry_run:
            save_state(state_path, latest, [])
        return 0

    if latest.trading_date <= last_checked:
        print(f"No new Cboe close after {last_checked.isoformat()}.")
        return 0

    crossings = detect_crossings(closes, after_date=last_checked)
    if crossings:
        title, description = build_message(crossings)
        print(title)
        print(description)
        if not dry_run:
            sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
            if not sendkey:
                raise RuntimeError("SERVERCHAN_SENDKEY is not configured")
            send_serverchan(sendkey, title, description)
            print("WeChat notification sent successfully.")
    else:
        print(
            f"Checked through {latest.trading_date.isoformat()}: "
            f"VIX close {latest.close:.2f}; no upward crossing."
        )

    if not dry_run:
        save_state(state_path, latest, crossings)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--dry-run", action="store_true", help="Do not notify or update state")
    parser.add_argument(
        "--test-notification",
        action="store_true",
        help="Send a WeChat test without downloading VIX data",
    )
    args = parser.parse_args()

    try:
        if args.test_notification:
            sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
            if not sendkey:
                raise RuntimeError("SERVERCHAN_SENDKEY is not configured")
            now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            send_serverchan(
                sendkey,
                "VIX监控测试成功",
                f"GitHub Actions与微信推送连接正常。\n\n测试时间：{now}",
            )
            print("Test notification sent successfully.")
            return 0
        return run_monitor(args.state, dry_run=args.dry_run)
    except Exception as exc:  # Keep workflow logs concise while returning failure.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
