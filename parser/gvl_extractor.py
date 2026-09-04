"""
parser/gvl_extractor.py

Обходит уже загруженное XML-дерево проекта (см. parser/xml_loader.py)
и извлекает "сырые" данные по ПЛК / GVL-блокам / переменным — без какой-
либо бизнес-логики отбора "быстрых параметров" (это задача
core/fast_param_finder.py).

Соответствует разделу 2 README (карта XPath).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

# XPath от корня документа до узлов ПЛК — намеренно точный (абсолютный)
# путь, а не ".//", потому что тег "configuration" в PLCopen-файле
# переиспользуется и для аппаратного дерева (Device/ProjectStructure),
# что мы подтвердили на реальном файле KA107__GPA2.plcopen.xml —
# широкий поиск ".//p:configuration" находил там 44 узла вместо одного.
_PLC_XPATH = "/p:project/p:instances/p:configurations/p:configuration"

# Внутри найденного узла ПЛК GVL-блоки ищем относительным путём —
# здесь двусмысленности с другими "globalVars" в документе не возникает,
# поэтому ".//" безопасен.
_GVL_XPATH = ".//p:resource/p:globalVars"

_VARIABLE_XPATH = "./p:variable"
_ATTRIBUTE_XPATH = "./p:addData/p:data/p:Attributes/p:Attribute"
_TYPE_XPATH = "./p:type/*"


@dataclass
class VariableInfo:
    """Данные одной переменной внутри GVL-блока."""

    name: str
    type_name: str
    # Атрибуты уровня самой переменной: {"symbol": "...", "export": "..."}.
    # Именно "сырые" значения (строки) — распарсенный export здесь
    # ещё не хранится, это будет сделано позже, в fast_param_finder.py,
    # только для переменных, реально прошедших первые условия отбора
    # (не тратим время на парсинг JSON5 для заведомо неподходящих).
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class GvlInfo:
    """Данные одного блока глобальных переменных (GVL)."""

    name: str
    # Атрибуты уровня самого GVL-блока — нужны для fallback по "symbol"
    # (условие 2 в README раздел 4: если у переменной атрибута symbol
    # нет, берётся атрибут symbol у родительского GVL).
    attributes: dict[str, str] = field(default_factory=dict)
    variables: list[VariableInfo] = field(default_factory=list)


@dataclass
class PlcInfo:
    """Данные одного ПЛК (узел configuration верхнего уровня)."""

    name: str
    gvls: list[GvlInfo] = field(default_factory=list)


def extract_plcs(tree: etree._ElementTree, ns: dict[str, str]) -> list[PlcInfo]:
    """
    Извлекает список ПЛК из распарсенного XML-дерева проекта.

    Параметры
    ---------
    tree, ns:
        Результат вызова parser.xml_loader.load_project_xml().

    Возвращает
    ----------
    Список PlcInfo — по одному на каждый узел
    /project/instances/configurations/configuration.
    Порядок соответствует порядку узлов в исходном XML (без сортировки —
    так требует заказчик, README раздел 1).
    """
    root = tree.getroot()
    plc_nodes = root.xpath(_PLC_XPATH, namespaces=ns)

    return [_extract_plc(node, ns) for node in plc_nodes]


def _extract_plc(plc_node: etree._Element, ns: dict[str, str]) -> PlcInfo:
    plc_name = plc_node.get("name") or ""
    gvl_nodes = plc_node.xpath(_GVL_XPATH, namespaces=ns)

    gvls = [_extract_gvl(node, ns) for node in gvl_nodes]

    return PlcInfo(name=plc_name, gvls=gvls)


def _extract_gvl(gvl_node: etree._Element, ns: dict[str, str]) -> GvlInfo:
    gvl_name = gvl_node.get("name") or ""
    gvl_attributes = _extract_attributes(gvl_node, ns)

    variable_nodes = gvl_node.xpath(_VARIABLE_XPATH, namespaces=ns)
    variables = [_extract_variable(node, ns) for node in variable_nodes]

    return GvlInfo(name=gvl_name, attributes=gvl_attributes, variables=variables)


def _extract_variable(var_node: etree._Element, ns: dict[str, str]) -> VariableInfo:
    var_name = var_node.get("name") or ""
    type_name = _extract_type_name(var_node, ns)
    var_attributes = _extract_attributes(var_node, ns)

    return VariableInfo(name=var_name, type_name=type_name, attributes=var_attributes)


def _extract_type_name(var_node: etree._Element, ns: dict[str, str]) -> str:
    """
    Реализует правило из README раздела 2 (карта XPath, п.4):
    тип переменной — значение атрибута "name", если тег узла типа —
    "derived"; иначе тип — имя самого тега узла.

    Пример: <type><REAL/></type>        -> тип "REAL"
            <type><derived name="ST_Foo"/></type> -> тип "ST_Foo"
    """
    type_children = var_node.xpath(_TYPE_XPATH, namespaces=ns)

    if not type_children:
        # В штатных PLCopen-файлах такого быть не должно, но на всякий
        # случай не роняем всю обработку из-за одной переменной без типа —
        # возвращаем маркер, который будет виден в CSV/логе как аномалия.
        return "<тип не определён>"

    type_node = type_children[0]
    local_tag = etree.QName(type_node).localname

    if local_tag == "derived":
        return type_node.get("name") or "<derived без имени>"

    return local_tag


def _extract_attributes(node: etree._Element, ns: dict[str, str]) -> dict[str, str]:
    """
    Извлекает узлы Attribute (README раздел 2, п.5) и складывает их
    в словарь {Name: Value}. Если бы в исходных данных встретился
    Attribute-узел без атрибута Name (аномалия), он просто игнорируется —
    так как без имени привязать его к бизнес-логике невозможно.
    """
    attribute_nodes = node.xpath(_ATTRIBUTE_XPATH, namespaces=ns)

    attributes: dict[str, str] = {}
    for attr_node in attribute_nodes:
        attr_name = attr_node.get("Name")
        attr_value = attr_node.get("Value")
        if attr_name is not None:
            attributes[attr_name] = attr_value if attr_value is not None else ""

    return attributes
