"""Preview keyset order: newest day, then binary UTF-8 identifiers."""


def follows_preview_key(key: tuple[str, ...], previous: tuple[str, ...]) -> bool:
    """Keys have already been validated against the dataset's public schema."""
    return key[0] < previous[0] or (
        key[0] == previous[0]
        and tuple(v.encode("utf-8") for v in key[1:])
        > tuple(v.encode("utf-8") for v in previous[1:])
    )
