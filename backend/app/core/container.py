from typing import Any, TypeVar, overload

T = TypeVar('T')


class ServiceContainer:
    """
    Simple Dependency Injection container to allow modules
    to share services without tight coupling.
    """

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        """Registers a service instance."""
        self._services[name] = service

    @overload
    def get(self, name: str) -> Any: ...

    @overload
    def get(self, name: str, expected_type: type[T]) -> T: ...

    def get(self, name: str, expected_type: type[T] | None = None) -> Any:
        """Retrieves a service by name, optionally with type validation."""
        service = self._services.get(name)
        if service is None:
            raise KeyError(f"Service '{name}' not found in container")
        if expected_type is not None and not isinstance(service, expected_type):
            raise TypeError(
                f"Service '{name}' is {type(service).__name__}, "
                f'expected {expected_type.__name__}'
            )
        return service


service_container = ServiceContainer()
