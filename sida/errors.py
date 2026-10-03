"""Application errors shared by the core and its front ends; no terminal I/O."""


class SidaError(Exception):
    """An application failure whose message and exit code are rendered by the caller."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code


def fail(message: str, code: int = 1) -> None:
    raise SidaError(message, code)
