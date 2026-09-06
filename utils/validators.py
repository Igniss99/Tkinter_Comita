"""
utils/validators.py

Проверки целостности данных, извлечённых parser/gvl_extractor.py —
выполняются ДО запуска core/fast_param_finder.py, чтобы поймать явные
проблемы во входных данных как можно раньше и сообщить о них
пользователю понятным текстом (требование ТЗ п.5).

Модуль не бросает исключения сам по себе — он собирает список найденных
проблем (ValidationIssue) и возвращает его вызывающему коду. Решение,
что делать дальше (прервать обработку или продолжить с предупреждением),
принимает вызывающий код (ui/main_window.py), а не сам валидатор —
так гибче: например, "0 ПЛК в файле" разумно считать фатальной ошибкой,
а "GVL без имени" — просто предупреждением.
"""

from __future__ import annotations

from dataclasses import dataclass

from parser.gvl_extractor import PlcInfo


@dataclass
class ValidationIssue:
    """Одна обнаруженная проблема с исходными данными."""

    severity: str  # "Error" | "Warning"
    message: str


def validate_plcs(plcs: list[PlcInfo]) -> list[ValidationIssue]:
    """
    Прогоняет все проверки целостности над списком ПЛК, извлечённых
    из XML, и возвращает список найденных проблем (может быть пустым,
    если данные в порядке).
    """
    issues: list[ValidationIssue] = []

    issues.extend(_check_at_least_one_plc(plcs))

    for plc in plcs:
        issues.extend(_check_plc_has_name(plc))
        issues.extend(_check_duplicate_gvl_names(plc))
        issues.extend(_check_gvl_and_variable_names(plc))

    return issues


def has_fatal_errors(issues: list[ValidationIssue]) -> bool:
    """Удобный шорткат: есть ли среди проблем хотя бы одна severity=Error."""
    return any(issue.severity == "Error" for issue in issues)


# ---------------------------------------------------------------------
# Отдельные проверки
# ---------------------------------------------------------------------

def _check_at_least_one_plc(plcs: list[PlcInfo]) -> list[ValidationIssue]:
    if not plcs:
        return [
            ValidationIssue(
                severity="Error",
                message=(
                    "В исходном файле не найдено ни одного ПЛК "
                    "(узел /project/instances/configurations/configuration). "
                    "Проверьте, что выбран корректный файл проекта Astra.IDE "
                    "в формате PLCopen."
                ),
            )
        ]
    return []


def _check_plc_has_name(plc: PlcInfo) -> list[ValidationIssue]:
    if not plc.name:
        return [
            ValidationIssue(
                severity="Error",
                message=(
                    "Найден узел ПЛК без имени (пустой атрибут name). "
                    "Это делает невозможным формирование имени CSV-файла "
                    "для данного ПЛК."
                ),
            )
        ]
    return []


def _check_duplicate_gvl_names(plc: PlcInfo) -> list[ValidationIssue]:
    """
    Заказчик подтвердил (README раздел 1, ответ №2): среда Codesys
    не допускает создание двух GVL с одинаковым именем внутри одного
    ПЛК, и если такое всё же встретится — это следует трактовать как
    ошибку исходных данных. Проверяем это явно, а не полагаемся молча
    на "такого не бывает" — файл мог быть повреждён или отредактирован
    вручную в обход штатных средств Codesys.
    """
    seen: dict[str, int] = {}
    for gvl in plc.gvls:
        seen[gvl.name] = seen.get(gvl.name, 0) + 1

    duplicates = [name for name, count in seen.items() if count > 1]
    if not duplicates:
        return []

    return [
        ValidationIssue(
            severity="Error",
            message=(
                f'ПЛК "{plc.name}": обнаружены повторяющиеся имена GVL-блоков: '
                f"{', '.join(duplicates)}. Согласно регламенту проекта такая "
                f"ситуация не должна возникать штатно — это признак "
                f"повреждённых исходных данных. Колонка «Путь» в CSV "
                f"перестаёт быть однозначной для этих блоков."
            ),
        )
    ]


def _check_gvl_and_variable_names(plc: PlcInfo) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for gvl in plc.gvls:
        if not gvl.name:
            issues.append(
                ValidationIssue(
                    severity="Warning",
                    message=(
                        f'ПЛК "{plc.name}": найден GVL-блок без имени '
                        f"(пустой атрибут name) — переменные внутри него "
                        f"получат путь вида \".{{имя переменной}}\"."
                    ),
                )
            )

        for var in gvl.variables:
            if not var.name:
                issues.append(
                    ValidationIssue(
                        severity="Warning",
                        message=(
                            f'ПЛК "{plc.name}", GVL "{gvl.name}": найдена '
                            f"переменная без имени (пустой атрибут name)."
                        ),
                    )
                )

    return issues
