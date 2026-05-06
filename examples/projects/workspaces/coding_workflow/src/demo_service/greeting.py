DEFAULT_NAME = "runtime"


def format_greeting(name: str | None = None) -> str:
    selected = (name or DEFAULT_NAME).strip()
    if not selected:
        selected = DEFAULT_NAME
    return f"Hello, {selected}."
