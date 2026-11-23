import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="epp", description="Eltern-Portal parser")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run web app, API, MCP and scheduler")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=3081)
    sub.add_parser("sync", help="One-off sync for development (credentials from EPP_TENANT/EPP_USERNAME/EPP_PASSWORD)")
    sub.add_parser("process", help="Extract attachment text and run analysis on already downloaded letters")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "serve":
        import uvicorn

        uvicorn.run("epp.api:app", host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")
        return

    from epp.credentials import Credentials
    from epp.services import credential_store, runner

    if args.command == "sync":
        credential_store.set(
            Credentials(tenant=os.environ["EPP_TENANT"], username=os.environ["EPP_USERNAME"],
                        password=os.environ["EPP_PASSWORD"])
        )
    print(runner.run_blocking(args.command).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
