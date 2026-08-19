from collections import deque


class ServiceUnavailableError(Exception):
    pass


class Router:
    def __init__(self, routing_table: dict[str, list[str]]) -> None:
        self._instances: dict[str, deque[str]] = {
            service: deque(instances) for service, instances in routing_table.items()
        }

    def next_instance(self, service_name: str) -> str:
        instances = self._instances.get(service_name)
        if not instances:
            raise ServiceUnavailableError(f"no instances registered for '{service_name}'")

        instance = instances[0]
        instances.rotate(-1)
        return instance
