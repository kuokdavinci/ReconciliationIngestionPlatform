"""FastAPI server startup."""

import asyncio

import uvicorn


def run_server(port: int = 8000) -> None:
    """Start the FastAPI server.

    Args:
        port: Port number for the server (default: 8000).
    """
    print(f"Starting FastAPI server on port {port}...")
    print(f"  API Docs: http://localhost:{port}/docs")
    print(f"  OpenAPI JSON: http://localhost:{port}/openapi.json")
    print("\nPress Ctrl+C to stop.\n")

    config = uvicorn.Config(
        "src.api:create_app",
        host="0.0.0.0",
        port=port,
        factory=True,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
