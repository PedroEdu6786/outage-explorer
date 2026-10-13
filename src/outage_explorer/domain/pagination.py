"""Pure numbered-page bounds for stable, addressable results."""


def validate_numbered_page(number: int, size: int | None = None) -> None:
    if type(number) is not int or number < 1:
        raise ValueError("Positive page required")
    if size is not None and (type(size) is not int or not 1 <= size <= 500):
        raise ValueError("Page size must be between one and 500")


def numbered_total_pages(size: int, total_rows: int) -> int:
    validate_numbered_page(1, size)
    if type(total_rows) is not int or total_rows < 0:
        raise ValueError("Nonnegative row count required")
    return max(1, (total_rows + size - 1) // size)


def numbered_window(number: int, size: int, total_rows: int) -> tuple[int, int]:
    validate_numbered_page(number, size)
    total_pages = numbered_total_pages(size, total_rows)
    if number > total_pages:
        raise ValueError("Page outside retained range")
    start = (number - 1) * size
    return start, min(start + size, total_rows)
