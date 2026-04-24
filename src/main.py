import argparse

from .config import load
from .scanner import run
from .telegram_bot import TelegramNotifier


def main() -> None:
    parser = argparse.ArgumentParser(description="機票價格掃描器")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="掃描但不發 Telegram 通知（印出會傳的內容）",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="發送一則測試訊息到 Telegram 後離開",
    )
    parser.add_argument(
        "--watch",
        metavar="NAME",
        help="只掃描 watchlist.yaml 中指定名稱的 watch（例如 --watch 大阪）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="印出每個日期組合的查詢結果（除錯用：看 API 是否有回資料）",
    )
    args = parser.parse_args()

    # --test-notify only needs Telegram credentials; skip the flights-API check
    # so users can verify their Telegram setup before finishing Travelpayouts signup.
    cfg = load(require_flights_api=not args.test_notify)

    if args.test_notify:
        notifier = TelegramNotifier(cfg.tg_bot_token, cfg.tg_chat_id)
        notifier.send("✅ 機票通知機器人連線正常！\n你已成功設定 Bot Token 與 Chat ID。")
        print("test notification sent")
        return

    if args.watch:
        cfg.watches = [w for w in cfg.watches if w.name == args.watch]
        if not cfg.watches:
            print(f"找不到 watch '{args.watch}'，請確認 watchlist.yaml 中的 name 欄位")
            return

    run(cfg, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
