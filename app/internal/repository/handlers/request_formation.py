def sort_formation(sort: str = "-pocket,id", keys: dict | None = None):
    sort_fields = [field.strip() for field in sort.split(",")]
    sort_params = []

    def add_sort(key: str, postfix: str):
        if keys is not None:
            if key in keys.keys():
                sort_params.append(f"{keys.get(key)} {postfix}")
        else:
            sort_params.append(f"{key} {postfix}")

    for field in sort_fields:
        field = field.strip()
        if field.startswith("-"):
            add_sort(field[1:], "desc")
        else:
            add_sort(field, "asc")

    return ", ".join(sort_params)


def paginate_formation(page: int = 1, size: int = 100):
    limit = size
    offset = (page - 1) * size
    return f"limit {limit} offset {offset}"
