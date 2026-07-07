from date_utils import parse_production_date
from production_summary import (
    format_shortage_summary,
    export_shortage_summary_excel,
)


def is_plan_shortage_summary_question(question: str):
    q = question.replace(" ", "")

    return (
        ("생산계획" in q or "계획" in q or "현재계획" in q)
        and ("부족" in q or "부족자재" in q or "자재부족" in q)
    )


def is_shortage_excel_question(question: str):
    q = question.replace(" ", "")

    return (
        ("엑셀" in q or "xlsx" in q or "파일" in q)
        and ("부족" in q or "부족자재" in q or "자재부족" in q)
    )


def handle_plan_shortage_summary(question: str):
    production_date = parse_production_date(question)

    return format_shortage_summary(
        production_date=production_date,
        only_shortage=True,
    )


def handle_shortage_excel(question: str):
    production_date = parse_production_date(question)

    success, msg, out_file = export_shortage_summary_excel(
        production_date=production_date,
        only_shortage=True,
    )

    if not success:
        return msg, None

    return msg, out_file