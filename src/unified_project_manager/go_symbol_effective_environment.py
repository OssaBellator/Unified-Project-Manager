from __future__ import annotations

from .go_symbol_source_observation import GoSymbolSourceObservation


def go_symbol_effective_goflags_blocker(
    observation: GoSymbolSourceObservation,
) -> str | None:
    """Return a fail-closed reason when effective GOFLAGS is not exactly empty.

    The source observation obtains this value from the same `go env -json`
    invocation that precedes package loading. Requiring an explicit empty value
    prevents real scanner-alignment gates from treating argv-only `tags=[]` as
    complete build-selection evidence when process or persisted Go configuration
    may inject default flags.
    """

    value = observation.build_environment.get("GOFLAGS")
    if value is None:
        return (
            "Go source observation is missing effective GOFLAGS; "
            "real scanner build-selection equivalence is not established"
        )
    if value:
        return (
            f"effective Go GOFLAGS is {value!r}, not empty; "
            "real scanner alignment does not override user GOFLAGS"
        )
    return None
