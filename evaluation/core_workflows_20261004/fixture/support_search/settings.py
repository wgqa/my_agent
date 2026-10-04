import os


DEFAULT_RESULT_LIMIT = 4


def load_result_limit():
    value = int(os.getenv("SUPPORT_RESULT_LIMIT", str(DEFAULT_RESULT_LIMIT)))
    if not 1 <= value <= 20:
        raise ValueError("SUPPORT_RESULT_LIMIT must be between 1 and 20")
    return value
