"""Development server entry point for the BiasRadar read API."""

import argparse

import uvicorn


def main() -> None:
    """Run the API; production deployments should use their process manager."""

    parser = argparse.ArgumentParser(description="Run the BiasRadar read API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()
    uvicorn.run(
        "biasradar.api.app:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
    )
