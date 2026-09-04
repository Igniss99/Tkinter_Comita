"""
parser/xml_loader.py

Отвечает за загрузку и первичную валидацию XML-файла проекта
(Astra.IDE / Codesys 3.5, формат PLCopen).

Ничего не знает про GVL/переменные/атрибуты — только:
  - открывает файл,
  - парсит его как XML,
  - определяет namespace корневого элемента,
  - отдаёт наружу дерево (etree) и словарь namespace, готовый
    для использования в XPath-запросах других модулей.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree


class XmlLoadError(Exception):
    """
    Единая ошибка загрузки XML-файла проекта.

    Оборачивает все возможные проблемы (файл не найден, не читается,
    невалидный XML) в одно понятное сообщение — чтобы GUI мог
    показать пользователю подробный текст ошибки (требование ТЗ п.5),
    не разбираясь, какое именно стандартное исключение прилетело.
    """


def load_project_xml(file_path: str | Path) -> tuple[etree._ElementTree, dict[str, str]]:
    """
    Загружает XML-файл проекта и определяет его namespace.

    Параметры
    ---------
    file_path:
        Путь к .xml файлу проекта (выбирается пользователем через
        диалоговое окно в GUI, см. ТЗ п.3a).

    Возвращает
    ----------
    (tree, ns) — кортеж:
        tree: lxml.etree._ElementTree — распарсенное дерево документа.
        ns:   dict — словарь namespace для использования в XPath,
              вида {"p": "http://www.plcopen.org/xml/tc6_0200"}.
              Если у корневого элемента нет namespace вовсе —
              возвращается пустой словарь {}.

    Исключения
    ----------
    XmlLoadError:
        если файл не существует, не является файлом, не читается,
        либо не парсится как валидный XML. Текст исключения содержит
        путь к файлу и исходную причину ошибки — для вывода в GUI.
    """
    path = Path(file_path)

    if not path.exists():
        raise XmlLoadError(f"Файл не найден: {path}")

    if not path.is_file():
        raise XmlLoadError(f"Указанный путь не является файлом: {path}")

    try:
        # resolve_entities=False и no_network=True — базовая защита от
        # потенциально вредоносного XML (XXE-подобные конструкции),
        # не влияет на разбор штатных PLCopen-файлов.
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        tree = etree.parse(str(path), parser=parser)
    except etree.XMLSyntaxError as exc:
        raise XmlLoadError(
            f"Файл повреждён или не является корректным XML: {path}\n"
            f"Причина: {exc}"
        ) from exc
    except OSError as exc:
        raise XmlLoadError(
            f"Не удалось прочитать файл: {path}\nПричина: {exc}"
        ) from exc

    root = tree.getroot()
    ns = _extract_namespace(root)

    return tree, ns


def _extract_namespace(root: etree._Element) -> dict[str, str]:
    """
    Определяет default-namespace корневого элемента и оборачивает его
    в словарь с искусственным префиксом "p" — потому что XPath 1.0
    (который использует lxml) не умеет работать с default-namespace
    напрямую, ему обязательно нужен именованный префикс в запросах
    вида ".//p:configuration".

    Если у корня namespace вообще не задан (что для PLCopen-файлов
    не ожидается, но на всякий случай) — возвращает пустой словарь,
    и вызывающий код должен использовать XPath без префиксов.
    """
    # У lxml namespace без префикса (default xmlns=...) хранится
    # в root.nsmap под ключом None.
    default_ns = root.nsmap.get(None)

    if default_ns is None:
        return {}

    return {"p": default_ns}