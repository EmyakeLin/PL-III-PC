"""Read named data from the current invocation without calling model methods."""

from collections.abc import Mapping


_STRICT = object()


def read_path(value, fields, *, missing=_STRICT):
    for field in fields:
        if not field.isidentifier() or field.startswith("_"):
            raise ValueError(f"无效的词条字段 {field!r}")
        if value is None:
            return None
        if isinstance(value, Mapping):
            value = value.get(field)
        else:
            try:
                value = getattr(value, field)
            except AttributeError as error:
                if missing is not _STRICT:
                    return missing
                raise ValueError(f"{type(value).__name__} 没有字段 {field!r}") from error
        if callable(value):
            raise ValueError(f"词条只能读取数据字段：{field}")
    return value
