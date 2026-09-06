"""
ui/main_window.py

Графический интерфейс приложения (README раздел 6):
  a. диалог выбора XML-файла проекта;
  b. диалог выбора каталога для результатов;
  c. кнопка запуска основного алгоритма;
  + область "журнал выполнения задачи ПО" (требование заказчика);
  + сообщение об успешном завершении;
  + сообщение об ошибке с подробностями.

Вся "тяжёлая" обработка (parser/*, core/*, output/*) выполняется в
отдельном потоке, чтобы окно не зависало на время работы с большим
XML-файлом. Поток кладёт результат в queue.Queue, а главный поток
Tkinter периодически проверяет очередь через root.after(...) —
это стандартный безопасный способ связать фоновый поток с GUI
в Tkinter (нельзя напрямую трогать виджеты из другого потока).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.fast_param_finder import analyze_project
from output.writer import WriterError, write_results
from parser.gvl_extractor import extract_plcs
from parser.xml_loader import XmlLoadError, load_project_xml
from utils.logger import TaskLogger
from utils.validators import has_fatal_errors, validate_plcs


@dataclass
class _TaskSuccess:
    written_files: list[Path]
    logger: TaskLogger


@dataclass
class _TaskFailure:
    message: str
    logger: TaskLogger


class MainWindow:
    """Главное окно приложения."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Список быстрых технологических параметров")
        self.root.geometry("720x520")
        self.root.minsize(600, 420)

        self._input_file_var = tk.StringVar()
        self._output_dir_var = tk.StringVar()
        self._result_queue: queue.Queue = queue.Queue()

        self._build_widgets()

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        padding = {"padx": 8, "pady": 6}

        # --- Выбор XML-файла проекта ---
        input_frame = ttk.Frame(self.root)
        input_frame.pack(fill="x", **padding)

        ttk.Label(input_frame, text="Файл проекта (.xml):").pack(anchor="w")
        row1 = ttk.Frame(input_frame)
        row1.pack(fill="x")
        ttk.Entry(row1, textvariable=self._input_file_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row1, text="Обзор...", command=self._choose_input_file).pack(
            side="left", padx=(6, 0)
        )

        # --- Выбор каталога результатов ---
        output_frame = ttk.Frame(self.root)
        output_frame.pack(fill="x", **padding)

        ttk.Label(output_frame, text="Каталог для результатов:").pack(anchor="w")
        row2 = ttk.Frame(output_frame)
        row2.pack(fill="x")
        ttk.Entry(row2, textvariable=self._output_dir_var, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row2, text="Обзор...", command=self._choose_output_dir).pack(
            side="left", padx=(6, 0)
        )

        # --- Кнопка запуска ---
        self._run_button = ttk.Button(
            self.root, text="Сформировать список параметров", command=self._on_run_clicked
        )
        self._run_button.pack(**padding)

        # --- Журнал выполнения ---
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, **padding)

        ttk.Label(log_frame, text="Журнал выполнения задачи ПО:").pack(anchor="w")

        text_container = ttk.Frame(log_frame)
        text_container.pack(fill="both", expand=True)

        self._log_text = tk.Text(text_container, height=15, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(
            text_container, orient="vertical", command=self._log_text.yview
        )
        self._log_text.configure(yscrollcommand=scrollbar.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Цветовые теги для разной severity — просто для читаемости журнала.
        self._log_text.tag_configure("Error", foreground="#b00020")
        self._log_text.tag_configure("Warning", foreground="#b06000")
        self._log_text.tag_configure("Info", foreground="#1a1a1a")

    # ------------------------------------------------------------------
    # Обработчики диалогов выбора
    # ------------------------------------------------------------------

    def _choose_input_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите файл проекта PLCopen",
            filetypes=[("XML файлы", "*.xml"), ("Все файлы", "*.*")],
        )
        if path:
            self._input_file_var.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Выберите каталог для результатов")
        if path:
            self._output_dir_var.set(path)

    # ------------------------------------------------------------------
    # Запуск обработки
    # ------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        input_file = self._input_file_var.get()
        output_dir = self._output_dir_var.get()

        if not input_file:
            messagebox.showerror("Ошибка", "Не выбран файл проекта (.xml).")
            return
        if not output_dir:
            messagebox.showerror("Ошибка", "Не выбран каталог для результатов.")
            return

        self._clear_log()
        self._set_running_state(True)

        thread = threading.Thread(
            target=self._run_task_in_background,
            args=(input_file, output_dir),
            daemon=True,
        )
        thread.start()

        # Начинаем опрашивать очередь на предмет результата фонового потока.
        self.root.after(100, self._poll_result_queue)

    def _run_task_in_background(self, input_file: str, output_dir: str) -> None:
        """
        Выполняется в отдельном потоке — не должен трогать виджеты Tkinter
        напрямую, только складывать результат в self._result_queue.
        """
        logger = TaskLogger()
        logger.info(f"Загрузка файла: {input_file}")

        try:
            tree, ns = load_project_xml(input_file)
        except XmlLoadError as exc:
            logger.error(str(exc))
            self._result_queue.put(_TaskFailure(message=str(exc), logger=logger))
            return

        plcs = extract_plcs(tree, ns)
        logger.info(f"Найдено ПЛК: {len(plcs)}")

        validation_issues = validate_plcs(plcs)
        for issue in validation_issues:
            if issue.severity == "Error":
                logger.error(issue.message)
            else:
                logger.warning(issue.message)

        if has_fatal_errors(validation_issues):
            message = (
                "Обнаружены критические проблемы во входных данных "
                "(см. журнал выполнения)."
            )
            self._result_queue.put(_TaskFailure(message=message, logger=logger))
            return

        results = analyze_project(plcs)
        for result in results:
            logger.add_from_fast_param_log(result.log_entries)
            logger.info(
                f'ПЛК "{result.plc_name}": найдено параметров — {len(result.rows)}'
            )

        try:
            written_files = write_results(results, output_dir)
        except WriterError as exc:
            logger.error(str(exc))
            self._result_queue.put(_TaskFailure(message=str(exc), logger=logger))
            return

        for f in written_files:
            logger.info(f"Записан файл: {f}")

        self._result_queue.put(_TaskSuccess(written_files=written_files, logger=logger))

    def _poll_result_queue(self) -> None:
        """
        Вызывается периодически из главного потока Tkinter (через
        root.after) — единственное безопасное место, откуда можно
        забирать результат фонового потока и обновлять виджеты.
        """
        try:
            result = self._result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result_queue)
            return

        self._render_log(result.logger)
        self._set_running_state(False)

        if isinstance(result, _TaskSuccess):
            file_list = "\n".join(str(f) for f in result.written_files)
            messagebox.showinfo(
                "Готово",
                f"Обработка завершена успешно.\n\nСоздано файлов: "
                f"{len(result.written_files)}\n{file_list}",
            )
        else:
            messagebox.showerror("Ошибка", result.message)

    # ------------------------------------------------------------------
    # Вспомогательные методы GUI
    # ------------------------------------------------------------------

    def _set_running_state(self, running: bool) -> None:
        self._run_button.configure(
            state="disabled" if running else "normal",
            text="Выполняется..." if running else "Сформировать список параметров",
        )

    def _clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _render_log(self, logger: TaskLogger) -> None:
        self._log_text.configure(state="normal")
        for record in logger.all_records():
            self._log_text.insert("end", record.format() + "\n", record.severity)
        self._log_text.configure(state="disabled")
        self._log_text.see("end")


def run_app() -> None:
    """Точка входа, вызывается из main.py."""
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
