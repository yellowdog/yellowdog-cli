"""
Adapted from:
  https://gist.github.com/jannismain/e96666ca4f059c3e5bc28abb711b5c92
"""

import json


class FloatAsWritten(float):
    """
    A JSON number with a fraction or exponent, keeping the text it was
    written as: json.loads(..., parse_float=FloatAsWritten) and the
    encoder below write '1.10' back as '1.10', not '1.1', and never round a
    value a double cannot hold exactly. yd-format-json, which must not
    change what a file says, is what reads with it.
    """

    text: str

    def __new__(cls, text: str) -> "FloatAsWritten":
        number = super().__new__(cls, text)
        number.text = text
        return number


class IntAsWritten(int):
    """
    A JSON integer keeping the text it was written as ('-0' stays '-0');
    see FloatAsWritten.
    """

    text: str

    def __new__(cls, text: str) -> "IntAsWritten":
        number = super().__new__(cls, text)
        number.text = text
        return number


class CompactJSONEncoder(json.JSONEncoder):
    """
    A JSON Encoder that puts small containers on single lines.
    """

    CONTAINER_TYPES = (list, tuple, dict)
    """Container datatypes include primitives or other containers."""

    MAX_WIDTH = 100
    """Maximum width of a container that might be put on a single line."""

    MAX_ITEMS = 10
    """Maximum number of items in container that might be put on single line."""

    def __init__(self, *args, **kwargs):
        # using this class without indentation is pointless
        if kwargs.get("indent") is None:
            kwargs.update({"indent": 4})
        super().__init__(*args, **kwargs)
        self.indentation_level = 0

    def encode(self, o):
        """
        Encode JSON object *o* with respect to single line lists.
        """
        if isinstance(o, (list, tuple)):
            single_line = self._single_line(o)
            if single_line is not None:
                return single_line
            self.indentation_level += 1
            output = [self.indent_str + self.encode(el) for el in o]
            self.indentation_level -= 1
            return "[\n" + ",\n".join(output) + "\n" + self.indent_str + "]"
        elif isinstance(o, dict):
            if not o:
                return "{}"
            single_line = self._single_line(o)
            if single_line is not None:
                return single_line
            self.indentation_level += 1
            output = [
                self.indent_str + f"{self._key(k)}: {self.encode(v)}"
                for k, v in o.items()
            ]
            self.indentation_level -= 1
            return "{\n" + ",\n".join(output) + "\n" + self.indent_str + "}"
        elif isinstance(o, (FloatAsWritten, IntAsWritten)):
            return o.text
        else:
            return json.dumps(o, ensure_ascii=self.ensure_ascii)

    def iterencode(self, o, **kwargs):
        """
        Required to also work with `json.dump`.
        """
        return self.encode(o)

    def _key(self, key) -> str:
        """
        A dict key as JSON writes one: always a string, as json.dumps()
        renders a non-string key ('1', 'true', 'null'), never bare.
        """
        if isinstance(key, str):
            text = key
        elif key is True or key is False:
            text = "true" if key else "false"
        elif key is None:
            text = "null"
        else:
            text = str(key)
        return json.dumps(text, ensure_ascii=self.ensure_ascii)

    def _single_line(self, o: list | tuple | dict) -> str | None:
        """
        The container on one line, if it holds only primitives, few enough
        of them, and the JSON written is narrow enough; None otherwise.
        """
        if not self._primitives_only(o) or len(o) > self.MAX_ITEMS:
            return None
        if isinstance(o, dict):
            text = (
                "{"
                + ", ".join(f"{self._key(k)}: {self.encode(v)}" for k, v in o.items())
                + "}"
            )
        else:
            text = "[" + ", ".join(self.encode(el) for el in o) + "]"
        return text if len(text) - 2 <= self.MAX_WIDTH else None

    def _primitives_only(self, o: list | tuple | dict) -> bool:
        if isinstance(o, (list, tuple)):
            return not any(isinstance(el, self.CONTAINER_TYPES) for el in o)
        elif isinstance(o, dict):
            return not any(isinstance(el, self.CONTAINER_TYPES) for el in o.values())
        else:
            return False

    @property
    def indent_str(self) -> str:
        if isinstance(self.indent, int):
            return " " * (self.indentation_level * self.indent)
        elif isinstance(self.indent, str):
            return self.indentation_level * self.indent
        else:
            raise ValueError(
                f"indent must either be of type int or str (is: {type(self.indent)})"
            )


if __name__ == "__main__":
    data = {
        "compact_object": {"first": "element", "second": 2},
        "compact_list": ["first", "second"],
        "long_list": ["this", "is", "a", "rather", "long", "list"],
    }
    print(json.dumps(data, cls=CompactJSONEncoder))
