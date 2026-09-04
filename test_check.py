from parser.xml_loader import load_project_xml

tree, ns = load_project_xml("KA107__GPA2.plcopen.xml")

print("Namespace:", ns)

root = tree.getroot()

# Точный путь, как указано в самом ТЗ
configs = root.xpath('/p:project/p:instances/p:configurations/p:configuration', namespaces=ns)
print("Найденные ПЛК (точный путь):", [c.get('name') for c in configs])