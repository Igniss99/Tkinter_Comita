"""
output/writer.py

Запись результатов анализа (core/fast_param_finder.PlcResult) в CSV-файлы —
по одному файлу на каждый ПЛК (README раздел 5).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from core.fast_param_finder import PlcResult

_CSV_HEADERS = ["Номер", "Путь", "Тип", "Имя"]

# Символы, недопустимые в имени файла на Windows: \ / : * ? " < > |
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


class WriterError(Exception):
    """
    Ошибка записи CSV-файла (нет прав на каталог, диск заполнен и т.п.) —
    оборачивает исходное исключение с понятным для пользователя текстом
    (требование ТЗ п.5 — подробное сообщение об ошибке).
    """


def write_results(results: list[PlcResult], output_dir: str | Path) -> list[Path]:
    """
    Записывает CSV-файл для каждого PlcResult в указанный каталог.

    Параметры
    ---------
    results:
        Список результатов анализа, по одному на ПЛК
        (core.fast_param_finder.analyze_project(...)).
    output_dir:
        Каталог для результатов — выбирается пользователем через
        диалоговое окно в GUI (README раздел 6, п.3b).

    Возвращает
    ----------
    Список путей к реально записанным CSV-файлам (для отображения
    в сообщении об успехе, README раздел 6, п.4).

    Исключения
    ----------
    WriterError — если каталог недоступен для записи или произошла
    ошибка ввода-вывода при записи конкретного файла.
    """
    out_path = Path(output_dir)

    if not out_path.exists():
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WriterError(
                f"Не удалось создать каталог результатов: {out_path}\nПричина: {exc}"
            ) from exc

    if not out_path.is_dir():
        raise WriterError(f"Указанный путь не является каталогом: {out_path}")

    written_files: list[Path] = []
    for result in results:
        file_path = _write_single_plc_csv(result, out_path)
        written_files.append(file_path)

    return written_files


def _write_single_plc_csv(result: PlcResult, out_path: Path) -> Path:
    file_name = _build_csv_filename(result.plc_name)
    file_path = out_path / file_name

    try:
        # utf-8-sig — добавляет BOM в начало файла. Без него Excel на
        # Windows по умолчанию открывает csv как cp1251/ANSI и кириллица
        # в заголовках/значениях превращается в кракозябры.
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(_CSV_HEADERS)
            for row in result.rows:
                writer.writerow(
                    [row.number, row.path, row.type_name, row.display_name]
                )
    except OSError as exc:
        raise WriterError(
            f"Не удалось записать файл результата: {file_path}\nПричина: {exc}"
        ) from exc

    return file_path


def _build_csv_filename(plc_name: str) -> str:
    """
    Формирует имя файла, содержащее имя ПЛК (README раздел 5:
    "Имя каждого файла должно содержать имя ПЛК"), с очисткой от
    символов, недопустимых в именах файлов Windows — на случай,
    если имя ПЛК в проекте когда-нибудь будет содержать что-то
    экзотическое.
    """
    safe_name = _INVALID_FILENAME_CHARS.sub("_", plc_name).strip()
    if not safe_name:
        safe_name = "PLC"
    return f"fast_params_{safe_name}.csv"
