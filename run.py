"""Reconciliation Ingestion Platform — CLI entrypoint.

Delegates to dedicated modules in cli/ and api/ directories.
"""

import argparse
import asyncio

from cli.ingest import run_ingestion
from cli.reconcile import run_reconciliation
from cli.scheduler import handle_scheduler_mode
from api.server import run_server


def main():
    parser = argparse.ArgumentParser(description="Reconciliation Ingestion Platform CLI")

    # Ingestion
    parser.add_argument("--data", type=str, help="Path to local data file (bypasses SFTP)")
    parser.add_argument("--config", type=str, help="Path to Excel template config")
    parser.add_argument("--partner", type=str, default="MOMO", help="Partner identifier")
    parser.add_argument("--date", type=str, help="Reconciliation date (YYYY-MM-DD)")

    # Reconciliation
    parser.add_argument("--reconcile", type=str, help="Run reconciliation (YYYY-MM-DD)")
    parser.add_argument("--seed-mock", action="store_true", help="Seed mock internal transactions")

    # Scheduler
    parser.add_argument("--start-scheduler", action="store_true", help="Start scheduler daemon")
    parser.add_argument("--run-job-now", action="store_true", help="Trigger daily fetch job")
    parser.add_argument("--list-jobs", action="store_true", help="List scheduled jobs")

    # Server
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--port", type=int, default=8000, help="API server port")

    args = parser.parse_args()

    # --serve runs synchronously (uvicorn manages its own event loop)
    if args.serve:
        run_server(port=args.port)
        return

    # All other commands require an async event loop
    if not any([args.reconcile, args.start_scheduler, args.run_job_now,
                args.list_jobs, args.data, args.config]):
        parser.print_help()
        return

    asyncio.run(_async_dispatch(args))


async def _async_dispatch(args):
    if args.reconcile:
        date = args.date or args.reconcile
        await run_reconciliation(args.partner, date, seed_mock=args.seed_mock)
    elif args.start_scheduler or args.run_job_now or args.list_jobs:
        await handle_scheduler_mode(
            start_scheduler=args.start_scheduler,
            run_job_now=args.run_job_now,
            list_jobs=args.list_jobs,
        )
    elif args.data or args.config:
        await run_ingestion(args)


if __name__ == "__main__":
    main()
