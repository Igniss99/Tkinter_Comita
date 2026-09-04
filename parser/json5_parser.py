"""
parser/json5_parser.py

Разбор кастомного формата "customJSON5", в котором записано значение
атрибута Attribute[@Name="export"] (см. README раздел 3).

Отличия от обычного JSON:
  - словари записаны в круглых скобках ( ) вместо фигурных { };
    круглые скобки ВНУТРИ строковых литералов не трогаются;
  - допустимы висячие запятые (JSON5-расширение);
  - допустимы ключи словаря без кавычек, если это валидный
    идентификатор (JSON5-расширение).

XML-экранирование (&quot; и т.п.) сюда попадать не должно — lxml
уже разворачивает entities при чтении значения атрибута из XML,
поэтому здесь мы работаем с обычной Python-строкой.

Модуль не зависит от сторонних библиотек (по требованию ТЗ
о минимальных зависимостях) — весь разбор написан на стандартных
средствах Python.
"""

from __future__ import annotations

from typing import Any


class Json5ParseError(Exception):
    """
    Ошибка разбора customJSON5.

    Сообщение содержит позицию (индекс символа) и краткое описание
    проблемы — этого достаточно, чтобы вызывающий код (core/fast_param_finder.py)
    сформировал предупреждение в журнале по шаблону, согласованному
    с заказчиком:
        "{nameGVL}.{nameVar}: Ошибка парсинга JSON атрибута "export": {текст ошибки}"
    """


def parse_export_json5(raw: str) -> Any:
    """
    Разбирает строку в формате customJSON5 и возвращает обычную
    Python-структуру (dict / list / str / float / int / bool / None).

    Параметры
    ---------
    raw:
        Значение атрибута export (уже без XML-экранирования — то,
        что вернул lxml через attr.get("Value")).

    Исключения
    ----------
    Json5ParseError — если строка не парсится как валидный customJSON5.
    """
    if raw is None or raw.strip() == "":
        raise Json5ParseError("пустое значение атрибута export")

    converted = _swap_brackets_outside_strings(raw)
    return _JsonFive(converted).parse_document()


def get_by_path(obj: Any, dotted_path: str) -> tuple[bool, Any]:
    """
    Достаёт значение из разобранной структуры по пути вида "a.b.c"
    (аналог упрощённого JSONPath без индексов массивов — большего
    в ТЗ и не требуется: используются только $.communication.cycle,
    $.name.full, $.name).

    Возвращает (найдено: bool, значение: Any).
    Если найдено=False — значение всегда None, ключа по пути нет
    (или структура на каком-то уровне не словарь) — это не ошибка,
    а штатный случай "элемент отсутствует", который вызывающий код
    (core/fast_param_finder.py) обрабатывает через fallback-цепочку.
    """
    current = obj
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


# ---------------------------------------------------------------------
# Шаг 1: замена скобок ( ) -> { } вне строковых литералов
# ---------------------------------------------------------------------

def _swap_brackets_outside_strings(text: str) -> str:
    """
    Проходит по строке посимвольно и заменяет '(' на '{', ')' на '}'
    только там, где мы НЕ находимся внутри строкового литерала
    в кавычках. Внутри строк (между непарными " с учётом экранирования
    \\") скобки остаются как есть — это тот самый нюанс, из-за которого
    наивный str.replace() был бы неверен.
    """
    result: list[str] = []
    in_string = False
    escaped = False

    for ch in text:
        if in_string:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
        elif ch == "(":
            result.append("{")
        elif ch == ")":
            result.append("}")
        else:
            result.append(ch)

    if in_string:
        raise Json5ParseError(
            "незакрытая строка (непарная кавычка) во входных данных"
        )

    return "".join(result)


# ---------------------------------------------------------------------
# Шаг 2: recursive-descent парсер получившегося JSON5-подобного текста
# ---------------------------------------------------------------------

_WHITESPACE = " \t\r\n"
_IDENTIFIER_START = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$"
)
_IDENTIFIER_CHARS = _IDENTIFIER_START | set("0123456789")


class _JsonFive:
    """
    Простой рекурсивный парсер JSON5-подмножества, которого достаточно
    для нашего формата: объекты, массивы, строки, числа, true/false/null,
    висячие запятые, ключи-идентификаторы без кавычек.

    Не претендует на полное покрытие спецификации JSON5 — только то,
    что реально встречается в customJSON5 данного проекта.
    """

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.length = len(text)

    # -- публичная точка входа -----------------------------------------

    def parse_document(self) -> Any:
        self._skip_whitespace()
        value = self._parse_value()
        self._skip_whitespace()
        if self.pos != self.length:
            raise Json5ParseError(
                f"лишние данные после конца значения, позиция {self.pos}"
            )
        return value

    # -- разбор значения любого типа -------------------------------------

    def _parse_value(self) -> Any:
        self._skip_whitespace()
        if self.pos >= self.length:
            raise Json5ParseError("неожиданный конец данных")

        ch = self.text[self.pos]

        if ch == "{":
            return self._parse_object()
        if ch == "[":
            return self._parse_array()
        if ch == '"':
            return self._parse_string()
        if ch == "-" or ch == "+" or ch.isdigit():
            return self._parse_number()
        if self.text.startswith("true", self.pos):
            self.pos += 4
            return True
        if self.text.startswith("false", self.pos):
            self.pos += 5
            return False
        if self.text.startswith("null", self.pos):
            self.pos += 4
            return None

        raise Json5ParseError(
            f"неожиданный символ {ch!r} на позиции {self.pos}"
        )

    # -- объект { ... } ---------------------------------------------------

    def _parse_object(self) -> dict:
        assert self.text[self.pos] == "{"
        self.pos += 1
        obj: dict[str, Any] = {}

        self._skip_whitespace()
        if self._peek() == "}":
            self.pos += 1
            return obj

        while True:
            self._skip_whitespace()
            key = self._parse_key()
            self._skip_whitespace()
            self._expect(":")
            self._skip_whitespace()
            value = self._parse_value()
            obj[key] = value

            self._skip_whitespace()
            ch = self._peek()
            if ch == ",":
                self.pos += 1
                self._skip_whitespace()
                if self._peek() == "}":  # висячая запятая
                    self.pos += 1
                    return obj
                continue
            if ch == "}":
                self.pos += 1
                return obj

            raise Json5ParseError(
                f"ожидалась ',' или '}}' на позиции {self.pos}, найдено {ch!r}"
            )

    def _parse_key(self) -> str:
        """Ключ словаря — либо строка в кавычках, либо голый идентификатор (JSON5)."""
        ch = self._peek()
        if ch == '"':
            return self._parse_string()

        if ch is None or ch not in _IDENTIFIER_START:
            raise Json5ParseError(
                f"ожидался ключ словаря на позиции {self.pos}, найдено {ch!r}"
            )

        start = self.pos
        while self.pos < self.length and self.text[self.pos] in _IDENTIFIER_CHARS:
            self.pos += 1
        return self.text[start:self.pos]

    # -- массив [ ... ] -----------------------------------------------------

    def _parse_array(self) -> list:
        assert self.text[self.pos] == "["
        self.pos += 1
        items: list[Any] = []

        self._skip_whitespace()
        if self._peek() == "]":
            self.pos += 1
            return items

        while True:
            self._skip_whitespace()
            items.append(self._parse_value())
            self._skip_whitespace()
            ch = self._peek()
            if ch == ",":
                self.pos += 1
                self._skip_whitespace()
                if self._peek() == "]":  # висячая запятая
                    self.pos += 1
                    return items
                continue
            if ch == "]":
                self.pos += 1
                return items

            raise Json5ParseError(
                f"ожидалась ',' или ']' на позиции {self.pos}, найдено {ch!r}"
            )

    # -- строка "..." -------------------------------------------------------

    def _parse_string(self) -> str:
        assert self.text[self.pos] == '"'
        self.pos += 1
        chars: list[str] = []

        while True:
            if self.pos >= self.length:
                raise Json5ParseError("незакрытая строка (конец данных)")
            ch = self.text[self.pos]

            if ch == '"':
                self.pos += 1
                return "".join(chars)

            if ch == "\\":
                self.pos += 1
                if self.pos >= self.length:
                    raise Json5ParseError("незакрытая escape-последовательность")
                esc = self.text[self.pos]
                mapping = {
                    '"': '"', "\\": "\\", "/": "/",
                    "n": "\n", "t": "\t", "r": "\r",
                    "b": "\b", "f": "\f",
                }
                if esc in mapping:
                    chars.append(mapping[esc])
                    self.pos += 1
                elif esc == "u":
                    hex_digits = self.text[self.pos + 1: self.pos + 5]
                    if len(hex_digits) != 4:
                        raise Json5ParseError(
                            f"некорректная \\u-последовательность на позиции {self.pos}"
                        )
                    chars.append(chr(int(hex_digits, 16)))
                    self.pos += 5
                else:
                    # Неизвестный escape — сохраняем символ как есть,
                    # не считаем это фатальной ошибкой формата.
                    chars.append(esc)
                    self.pos += 1
                continue

            chars.append(ch)
            self.pos += 1

    # -- число ---------------------------------------------------------------

    def _parse_number(self) -> int | float:
        start = self.pos
        if self._peek() in ("-", "+"):
            self.pos += 1

        while self.pos < self.length and self.text[self.pos].isdigit():
            self.pos += 1

        is_float = False
        if self._peek() == ".":
            is_float = True
            self.pos += 1
            while self.pos < self.length and self.text[self.pos].isdigit():
                self.pos += 1

        if self._peek() in ("e", "E"):
            is_float = True
            self.pos += 1
            if self._peek() in ("+", "-"):
                self.pos += 1
            while self.pos < self.length and self.text[self.pos].isdigit():
                self.pos += 1

        token = self.text[start:self.pos]
        if token in ("", "-"):
            raise Json5ParseError(f"некорректное число на позиции {start}")

        return float(token) if is_float else int(token)

    # -- вспомогательное -------------------------------------------------------

    def _peek(self) -> str | None:
        return self.text[self.pos] if self.pos < self.length else None

    def _expect(self, ch: str) -> None:
        if self._peek() != ch:
            raise Json5ParseError(
                f"ожидался символ {ch!r} на позиции {self.pos}, найдено {self._peek()!r}"
            )
        self.pos += 1

    def _skip_whitespace(self) -> None:
        while self.pos < self.length and self.text[self.pos] in _WHITESPACE:
            self.pos += 1
