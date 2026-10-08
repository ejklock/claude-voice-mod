class ProviderUnavailable(Exception):
    """An adapter cannot run here; raised by its constructor before any work."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
