"""Lock a synchronous instance method for the duration of one call."""

from collections.abc import Callable
from functools import wraps
from typing import Concatenate, cast


def with_instance_lock[S, **P, T](
    attribute: str,
) -> Callable[[Callable[Concatenate[S, P], T]], Callable[Concatenate[S, P], T]]:
    """Use the instance's named context-manager lock around a method call.

    Decorate short, synchronous operations. For context managers, decorate
    reservation and release methods separately so caller work remains unlocked.
    """

    def decorate(
        method: Callable[Concatenate[S, P], T],
    ) -> Callable[Concatenate[S, P], T]:
        @wraps(method)
        def wrapper(self: S, *args: P.args, **kwargs: P.kwargs) -> T:
            with getattr(self, attribute):
                return method(self, *args, **kwargs)

        return cast("Callable[Concatenate[S, P], T]", wrapper)

    return decorate
