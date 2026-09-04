from parser.xml_loader import load_project_xml
from parser.gvl_extractor import extract_plcs
from core.fast_param_finder import analyze_project
from output.writer import write_results

tree, ns = load_project_xml("KA107__GPA2.plcopen.xml")
plcs = extract_plcs(tree, ns)
results = analyze_project(plcs)

for result in results:
    print(f"=== ПЛК: {result.plc_name} ===")
    print(f"Найдено 'быстрых параметров': {len(result.rows)}")
    print(f"Записей в журнале (warnings): {len(result.log_entries)}")

    print("\nСтроки CSV:")
    for row in result.rows:
        print(f"  {row.number}\t{row.path}\t{row.type_name}\t{row.display_name}")

    print(f"\nПервые 3 записи журнала:")
    for entry in result.log_entries[:3]:
        print(f"  [{entry.severity}] {entry.message}")

written = write_results(results, "test_output")
print("\nЗаписанные файлы:")
for f in written:
    print(" -", f)