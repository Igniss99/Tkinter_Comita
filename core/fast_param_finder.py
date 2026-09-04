"""
core/fast_param_finder.py

Бизнес-логика отбора "быстрых технологических параметров" (README раздел 4)
и формирования строк для CSV-выгрузки (README раздел 5).

Ничего не знает про XML или про формат customJSON5 напрямую — работает
уже с извлечёнными структурами PlcInfo/GvlInfo/VariableInfo из
parser/gvl_extractor.py, и вызывает parser/json5_parser.py только тогда,
когда это действительно нужно (переменная имеет атрибут export).
"""

from __future__ import annotations

from dataclasses import dataclass

from parser.gvl_extractor import GvlInfo, PlcInfo, VariableInfo
from parser.json5_parser import Json5ParseError, get_by_path, parse_export_json5


@dataclass
class FastParamRow:
    """Одна строка будущего CSV-файла (README раздел 5)."""

    number: int
    path: str
    type_name: str
    display_name: str


@dataclass
class LogEntry:
    """
    Запись для "журнала выполнения задачи ПО" (требование заказчика,
    README раздел 1 п.3 и раздел 6 п.6).
    """

    severity: str  # "Warning" | "Error" | "Info" — используем как есть
    message: str


@dataclass
class PlcResult:
    """Результат обработки одного ПЛК: строки для его CSV + записи лога."""

    plc_name: str
    rows: list[FastParamRow]
    log_entries: list[LogEntry]


def analyze_project(plcs: list[PlcInfo]) -> list[PlcResult]:
    """
    Обрабатывает все ПЛК проекта. Возвращает по одному PlcResult на
    каждый ПЛК — ровно то количество, что нужно для создания CSV-файлов
    (README раздел 5: "количество файлов равно количеству ПЛК").
    """
    return [_analyze_plc(plc) for plc in plcs]


def _analyze_plc(plc: PlcInfo) -> PlcResult:
    rows: list[FastParamRow] = []
    log_entries: list[LogEntry] = []
    number = 1

    # Порядок обхода — как в XML-дереве, без сортировки (README раздел 1,
    # ответ заказчика на вопрос №1). gvl_extractor уже сохраняет этот
    # порядок, здесь достаточно просто идти по спискам как есть.
    for gvl in plc.gvls:
        for var in gvl.variables:
            row, entry = _evaluate_variable(gvl, var, number)
            if entry is not None:
                log_entries.append(entry)
            if row is not None:
                rows.append(row)
                number += 1

    return PlcResult(plc_name=plc.name, rows=rows, log_entries=log_entries)


def _evaluate_variable(
    gvl: GvlInfo, var: VariableInfo, next_number: int
) -> tuple[FastParamRow | None, LogEntry | None]:
    """
    Проверяет три условия README раздела 4 для одной переменной.

    Возвращает (row, log_entry):
      - row — FastParamRow, если переменная прошла все условия, иначе None;
      - log_entry — запись для журнала, если по ходу проверки обнаружена
        проблема с данными (битый export), иначе None.

    Условие 1 (переменная объявлена внутри GVL) выполнено автоматически —
    мы и так итерируемся по var внутри gvl.
    """
    # --- Условие 2: symbol != "none", с fallback на уровень GVL ---
    symbol_value = var.attributes.get("symbol")
    if symbol_value is None:
        symbol_value = gvl.attributes.get("symbol")

    if symbol_value is None or symbol_value == "none":
        return None, None

    # --- Условие 3: export есть, парсится, communication.cycle == fast ---
    export_raw = var.attributes.get("export")
    if export_raw is None:
        # У переменной вообще нет атрибута export — это штатная ситуация
        # (не все переменные экспортируются), не ошибка, лог не нужен.
        return None, None

    try:
        parsed = parse_export_json5(export_raw)
    except Json5ParseError as exc:
        # Битый export у переменной — по требованию заказчика логируем
        # предупреждение по согласованному шаблону (README раздел 1, п.3).
        message = (
            f'{gvl.name}.{var.name}: Ошибка парсинга JSON атрибута "export": {exc}'
        )
        return None, LogEntry(severity="Warning", message=message)

    found_cycle, cycle_value = get_by_path(parsed, "communication.cycle")
    if not found_cycle or not isinstance(cycle_value, str):
        return None, None
    if cycle_value.lower() != "fast":
        return None, None

    # --- Переменная прошла все условия — формируем строку CSV ---
    display_name = _resolve_display_name(parsed)
    path = f"{gvl.name}.{var.name}"

    row = FastParamRow(
        number=next_number,
        path=path,
        type_name=var.type_name,
        display_name=display_name,
    )
    return row, None


def _resolve_display_name(parsed_export: object) -> str:
    """
    Реализует fallback-цепочку колонки "Имя" (README раздел 5):
    $.name.full -> $.name -> "---".

    $.name может оказаться и строкой (простой случай), и словарём
    (если у него есть вложенный "full") — обе ветки предусмотрены.
    """
    found_full, name_full = get_by_path(parsed_export, "name.full")
    if found_full and isinstance(name_full, str) and name_full != "":
        return name_full

    found_name, name_value = get_by_path(parsed_export, "name")
    if found_name and isinstance(name_value, str) and name_value != "":
        return name_value

    return "---"
