"""
utils/logger.py

Простой накопитель сообщений для "журнала выполнения задачи ПО"
(требование заказчика, README раздел 1 п.3 и раздел 6 п.6).

Не зависит от GUI-библиотеки напрямую — просто копит записи в списке.
ui/main_window.py потом сам решает, как их отрисовать (например,
построчно в Text-виджет Tkinter, с разным цветом по severity).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class LogRecord:
    """Одна запись журнала с меткой времени."""

    timestamp: datetime
    severity: str  # "Info" | "Warning" | "Error"
    message: str

    def format(self) -> str:
        """Готовая строка для вывода в текстовое поле GUI или в консоль."""
        time_str = self.timestamp.strftime("%H:%M:%S")
        return f"[{time_str}] [{self.severity}] {self.message}"


class TaskLogger:
    """
    Копит записи журнала за время выполнения одной задачи (один запуск
    обработки файла). Создаётся заново на каждый запуск в GUI, чтобы
    не накапливать историю между разными файлами без необходимости.
    """

    def __init__(self) -> None:
        self._records: list[LogRecord] = []

    def info(self, message: str) -> None:
        self._add("Info", message)

    def warning(self, message: str) -> None:
        self._add("Warning", message)

    def error(self, message: str) -> None:
        self._add("Error", message)

    def add_from_fast_param_log(self, entries: list) -> None:
        """
        Принимает список LogEntry из core.fast_param_finder (у него
        свои простые объекты severity/message, без временной метки)
        и добавляет их в общий журнал с меткой времени "сейчас".

        Аргумент типизирован как list, а не list[LogEntry], чтобы
        этот модуль не тянул зависимость на core/ — журнал должен
        уметь работать независимо от бизнес-логики, которая его
        наполняет (принцип "низкая связанность между слоями").
        """
        for entry in entries:
            self._add(entry.severity, entry.message)

    def has_errors(self) -> bool:
        return any(r.severity == "Error" for r in self._records)

    def has_warnings(self) -> bool:
        return any(r.severity == "Warning" for r in self._records)

    def all_records(self) -> list[LogRecord]:
        return list(self._records)

    def format_all(self) -> str:
        """Все записи журнала одной строкой с переносами — удобно
        для разового вывода в Text-виджет Tkinter."""
        return "\n".join(r.format() for r in self._records)

    def _add(self, severity: str, message: str) -> None:
        self._records.append(
            LogRecord(timestamp=datetime.now(), severity=severity, message=message)
        )
