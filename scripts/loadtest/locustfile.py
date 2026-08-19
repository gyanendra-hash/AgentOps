import uuid

from locust import HttpUser, between, task


class GatewayUser(HttpUser):
    wait_time = between(0.01, 0.1)

    def on_start(self) -> None:
        self.client_id = f"loadtest-{uuid.uuid4().hex[:8]}"

    @task
    def ping(self) -> None:
        self.client.get(
            "/api/ping",
            headers={"X-Client-Id": self.client_id},
            name="/api/ping",
        )
