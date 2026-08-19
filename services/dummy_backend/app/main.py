from fastapi import FastAPI, Request

app = FastAPI(title="AgentOps Dummy Backend")


@app.get("/ping")
async def ping() -> dict:
    return {"pong": True}


@app.api_route("/echo", methods=["GET", "POST"])
async def echo(request: Request) -> dict:
    body = await request.body()
    return {
        "method": request.method,
        "path": str(request.url.path),
        "query": dict(request.query_params),
        "body": body.decode("utf-8", errors="replace"),
    }
