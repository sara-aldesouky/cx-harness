"""Presentation-grade XLSX rendering without recalculating report evidence."""

import io
from decimal import Decimal
from typing import Any, Iterable

import xlsxwriter

from .csv_exporter import safe_cell
from .tables import comparison_tables, run_tables


NAVY = "#0B2942"
TEAL = "#0E7490"
BLUE = "#2563EB"
GREEN = "#16A34A"
AMBER = "#D97706"
RED = "#DC2626"
LIGHT_BLUE = "#EAF4F8"
LIGHT_GREEN = "#ECFDF3"
LIGHT_RED = "#FEF2F2"
GRID = "#D6DEE5"


class ExcelExporter:
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def render_run(self, report, case_evidence: Iterable[Any] = ()) -> bytes:
        return self._render(run_tables(report), report=report, case_evidence=tuple(case_evidence))

    def render_comparison(self, report) -> bytes:
        return self._render(comparison_tables(report), comparison=report)

    def _formats(self, workbook):
        return {
            "title": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": NAVY, "font_size": 18, "align": "center", "valign": "vcenter"}),
            "subtitle": workbook.add_format({"font_color": "#D7E7F2", "bg_color": NAVY, "font_size": 9, "align": "center", "valign": "vcenter"}),
            "section": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": TEAL, "font_size": 10, "align": "center", "valign": "vcenter", "border": 1, "border_color": GRID}),
            "header": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": NAVY, "border": 1, "border_color": GRID, "text_wrap": True, "align": "center", "valign": "vcenter"}),
            "body": workbook.add_format({"valign": "top", "text_wrap": True, "border": 1, "border_color": GRID, "font_size": 9}),
            "center": workbook.add_format({"align": "center", "valign": "vcenter", "border": 1, "border_color": GRID, "font_size": 9}),
            "percent": workbook.add_format({"num_format": "0.0%", "align": "center", "border": 1, "border_color": GRID}),
            "number": workbook.add_format({"num_format": "0.00", "align": "center", "border": 1, "border_color": GRID}),
            "kpi_label": workbook.add_format({"bold": True, "font_color": "#52606D", "bg_color": "#F5F8FA", "align": "center", "border": 1, "border_color": GRID, "font_size": 9}),
            "kpi_value": workbook.add_format({"bold": True, "font_color": NAVY, "bg_color": "#FFFFFF", "align": "center", "valign": "vcenter", "border": 1, "border_color": GRID, "font_size": 14}),
            "pass": workbook.add_format({"bold": True, "font_color": "#166534", "bg_color": LIGHT_GREEN, "align": "center", "border": 1, "border_color": GRID}),
            "fail": workbook.add_format({"bold": True, "font_color": "#991B1B", "bg_color": LIGHT_RED, "align": "center", "border": 1, "border_color": GRID}),
            "unavailable": workbook.add_format({"font_color": "#667085", "italic": True, "valign": "top", "text_wrap": True, "border": 1, "border_color": GRID}),
            "note": workbook.add_format({"font_color": "#475467", "bg_color": "#F8FAFC", "text_wrap": True, "valign": "vcenter", "border": 1, "border_color": GRID, "font_size": 9}),
        }

    def _render(self, tables, report=None, case_evidence=(), comparison=None) -> bytes:
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True, "constant_memory": False})
        workbook.set_properties({"title": "CX Harness benchmark report", "company": "CX Harness", "comments": "Presentation-only export of stored benchmark evidence"})
        formats = self._formats(workbook)
        if report is not None:
            self._executive_summary(workbook, report, formats)
            self._test_evidence(workbook, report, case_evidence, formats)
            self._scoring_guide(workbook, report, formats)
            tables = tuple((name, rows) for name, rows in tables if name != "Executive Summary")
        elif comparison is not None:
            self._comparison_summary(workbook, comparison, formats)
            tables = tuple((name, rows) for name, rows in tables if name != "Executive Summary")
        for sheet_name, rows in tables:
            self._generic_sheet(workbook, sheet_name, rows, formats)
        workbook.close()
        return output.getvalue()

    def _sheet_title(self, sheet, title, subtitle, formats, last_col=11):
        sheet.hide_gridlines(2)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.set_margins(0.25, 0.25, 0.4, 0.4)
        sheet.merge_range(0, 0, 1, last_col, title, formats["title"])
        sheet.merge_range(2, 0, 2, last_col, subtitle, formats["subtitle"])
        sheet.set_row(0, 24)
        sheet.set_row(1, 24)

    def _executive_summary(self, workbook, report, formats):
        sheet = workbook.add_worksheet("Executive Summary")
        self._sheet_title(sheet, "CX Harness Model Evaluation", f"{report.suite_key} v{report.suite_version} · {report.run.provider_name} / {report.run.model_name}", formats)
        passed = int(report.completion.passed_cases)
        failed = int(report.completion.failed_cases)
        cost = report.cost.average_cost_per_conversation
        critical = report.reliability.conversations_with_security_failures + report.reliability.conversations_with_infrastructure_failures
        kpis = [
            ("Overall Winner", report.run.model_name),
            ("Overall Score", report.performance.overall_score),
            ("Pass Rate", report.completion.pass_rate),
            ("Critical Failure Rate", Decimal(critical) / Decimal(report.completion.stored_test_cases) if report.completion.stored_test_cases else None),
            ("Average Latency", report.latency.average_conversation_latency_ms),
            ("Average Cost", cost),
        ]
        for index, (label, value) in enumerate(kpis):
            col = index * 2
            sheet.merge_range(4, col, 4, col + 1, label, formats["kpi_label"])
            display = "Unavailable" if value is None else float(value) if isinstance(value, Decimal) else value
            sheet.merge_range(5, col, 6, col + 1, display, formats["kpi_value"] if value is not None else formats["unavailable"])
        recommendation = "Best overall candidate" if report.completion.pass_rate is not None and report.completion.pass_rate >= Decimal("0.90") else "Promising candidate — investigate failed cases" if report.completion.pass_rate is not None and report.completion.pass_rate >= Decimal("0.75") else "Not ready — material quality gaps"
        sheet.merge_range("A8:L8", f"Recommendation: {recommendation}. Conclusions use stored scoring evidence only.", formats["note"])

        score_data = [["Model", "Overall Score"], [report.run.model_name, float(report.performance.overall_score or 0)]]
        criteria = [["Criterion", "Score"]] + [[component.dimension.replace("_", " ").title(), float(component.score)] for component in report.performance.weighted_components]
        distribution = [["Outcome", "Cases"], ["Passed", passed], ["Failed", failed]]
        efficiency = [["Metric", report.run.model_name], ["Avg latency (ms)", float(report.latency.average_conversation_latency_ms or 0)], ["Avg cost", float(cost or 0)], ["Tool success rate", float(report.execution.tool_execution_success_rate or 0)], ["Hallucination rate", float(report.hallucination.hallucination_rate or 0)], ["Grounding rate", float(report.grounding.grounding_pass_rate or 0)]]
        sheet.write_row("N1", score_data[0]); sheet.write_row("N2", score_data[1])
        for row, values in enumerate(criteria): sheet.write_row(row, 16, values)
        for row, values in enumerate(distribution): sheet.write_row(row, 19, values)
        for row, values in enumerate(efficiency): sheet.write_row(row, 22, values)
        # Keep chart source cells visible: Excel can plot hidden ranges when
        # configured, but Numbers intentionally drops those series on import.
        # They remain outside the print area and are visually de-emphasized.
        helper = workbook.add_format({"font_color": "#94A3B8", "font_size": 8})
        sheet.set_column("N:X", 3, helper)

        score_chart = workbook.add_chart({"type": "column"})
        score_chart.add_series({"name": "Overall score", "categories": "='Executive Summary'!$N$2:$N$2", "values": "='Executive Summary'!$O$2:$O$2", "fill": {"color": TEAL}, "border": {"none": True}, "data_labels": {"value": True, "num_format": "0%"}})
        score_chart.set_title({"name": "Overall Score by Model"}); score_chart.set_y_axis({"min": 0, "max": 1, "num_format": "0%", "major_gridlines": {"visible": True, "line": {"color": "#E5E7EB"}}}); score_chart.set_legend({"none": True}); score_chart.set_style(10); score_chart.set_size({"width": 510, "height": 270})
        sheet.insert_chart("A10", score_chart)

        criterion_chart = workbook.add_chart({"type": "column"})
        end = len(criteria)
        criterion_chart.add_series({"name": report.run.model_name, "categories": f"='Executive Summary'!$Q$2:$Q${end}", "values": f"='Executive Summary'!$R$2:$R${end}", "fill": {"color": BLUE}, "border": {"none": True}})
        criterion_chart.set_title({"name": "Performance by Criterion"}); criterion_chart.set_y_axis({"min": 0, "max": 1, "num_format": "0%"}); criterion_chart.set_legend({"none": True}); criterion_chart.set_style(10); criterion_chart.set_size({"width": 510, "height": 270})
        sheet.insert_chart("G10", criterion_chart)

        outcome_chart = workbook.add_chart({"type": "doughnut"})
        outcome_chart.add_series({"name": "Cases", "categories": "='Executive Summary'!$T$2:$T$3", "values": "='Executive Summary'!$U$2:$U$3", "points": [{"fill": {"color": GREEN}}, {"fill": {"color": RED}}], "data_labels": {"percentage": True, "category": True}})
        outcome_chart.set_title({"name": "Pass vs Fail Distribution"}); outcome_chart.set_hole_size(55); outcome_chart.set_style(10); outcome_chart.set_size({"width": 380, "height": 250})
        sheet.insert_chart("A25", outcome_chart)

        metric_chart = workbook.add_chart({"type": "bar"})
        metric_chart.add_series({"name": report.run.model_name, "categories": "='Executive Summary'!$W$4:$W$6", "values": "='Executive Summary'!$X$4:$X$6", "fill": {"color": AMBER}, "border": {"none": True}, "data_labels": {"value": True, "num_format": "0%"}})
        metric_chart.set_title({"name": "Tool Success, Hallucination & Grounding"}); metric_chart.set_x_axis({"min": 0, "max": 1, "num_format": "0%"}); metric_chart.set_legend({"none": True}); metric_chart.set_style(10); metric_chart.set_size({"width": 630, "height": 250})
        sheet.insert_chart("F25", metric_chart)
        sheet.set_column("A:L", 12)
        sheet.print_area("A1:L39")
        sheet.freeze_panes(4, 0)

    def _test_evidence(self, workbook, report, evidence, formats):
        sheet = workbook.add_worksheet("Model Test Evidence")
        self._sheet_title(sheet, "Model Test Evidence", "Stored customer questions, model answers, tool evidence, outcomes, and measured efficiency", formats, 17)
        columns = ["Test Case ID", "Language", "Category", "Customer Question", "Model", "Model Response", "Pass / Fail", "Hallucination", "Grounded", "Correct Tool", "Tool Used", "Intent Match", "Latency (ms)", "Tokens", "Cost", "Failure Category", "Failure Explanation", "Expected Answer"]
        sheet.write_row(4, 0, columns, formats["header"])
        for row_index, item in enumerate(evidence, start=5):
            values = [item.test_case_id, item.language, item.category, item.customer_question, item.model, item.model_response, "PASS" if item.passed else "FAIL", "✓" if item.hallucination else "✗", "✓" if item.grounded else "✗", "Unavailable" if item.correct_tool is None else "✓" if item.correct_tool else "✗", ", ".join(item.tool_used) or "None", "Unavailable" if item.intent_match is None else "✓" if item.intent_match else "✗", float(item.latency_ms), item.tokens, "Unavailable" if item.cost is None else f"{item.cost} {item.currency_code}", item.failure_category or "None", item.failure_explanation or "None", item.expected_answer or "Not available"]
            for col, value in enumerate(values):
                cell_format = formats["pass"] if col == 6 and item.passed else formats["fail"] if col == 6 else formats["body"]
                sheet.write(row_index, col, safe_cell(value), cell_format)
            sheet.set_row(row_index, 72 if len(item.customer_question) + len(item.model_response) > 180 else 45)
        if not evidence:
            sheet.merge_range("A6:R8", "No case-level evidence is available for this run. Future benchmark executions must retain a source conversation to include question and answer text.", formats["unavailable"])
        sheet.freeze_panes(5, 3)
        sheet.autofilter(4, 0, max(5, 4 + len(evidence)), len(columns) - 1)
        widths = [15, 16, 18, 42, 18, 58, 12, 13, 12, 13, 24, 13, 14, 11, 14, 20, 38, 38]
        for col, width in enumerate(widths): sheet.set_column(col, col, width)
        sheet.set_row(4, 34)
        sheet.set_landscape(); sheet.fit_to_pages(1, 0); sheet.repeat_rows(0, 4)
        sheet.print_area(0, 0, max(8, 4 + len(evidence)), len(columns) - 1)

    def _scoring_guide(self, workbook, report, formats):
        sheet = workbook.add_worksheet("Scoring Guide")
        self._sheet_title(sheet, "Scoring Guide", "The exact scoring components applied to this benchmark run", formats, 7)
        headers = ["Criterion", "Score", "Configured Weight", "Effective Weight", "Weighted Score", "Evidence Status", "Interpretation", "Notes"]
        sheet.write_row(4, 0, headers, formats["header"])
        for row, item in enumerate(report.performance.weighted_components, start=5):
            interpretation = "Strong" if item.score >= Decimal("0.85") else "Acceptable" if item.score >= Decimal("0.70") else "Needs attention"
            sheet.write_row(row, 0, [item.dimension.replace("_", " ").title(), float(item.score), float(item.configured_weight), float(item.effective_weight), float(item.weighted_score), "Measured", interpretation, "Derived by the existing scoring engine"], formats["body"])
        final = 5 + len(report.performance.weighted_components)
        sheet.merge_range(final + 1, 0, final + 1, 7, "Unavailable metrics are excluded and remaining weights are normalized according to the stored scoring policy. This workbook does not recalculate scores.", formats["note"])
        sheet.set_column("A:A", 28); sheet.set_column("B:E", 18); sheet.set_column("F:G", 18); sheet.set_column("H:H", 42)
        sheet.freeze_panes(5, 0)

    def _comparison_summary(self, workbook, report, formats):
        sheet = workbook.add_worksheet("Executive Summary")
        self._sheet_title(sheet, "CX Harness Model Comparison", f"{report.suite_key} v{report.suite_version} · evidence-based comparison", formats)
        headers = ["Model", "Provider", "Overall Score", "Pass Rate", "Avg Latency (ms)", "Avg Cost"]
        sheet.write_row(4, 0, headers, formats["header"])
        for row, run in enumerate(report.runs, start=5):
            sheet.write_row(row, 0, [run.run.model_name, run.run.provider_name, float(run.performance.overall_score or 0), float(run.completion.pass_rate or 0), float(run.latency.average_conversation_latency_ms or 0), "Unavailable" if run.cost.average_cost_per_conversation is None else float(run.cost.average_cost_per_conversation)], formats["body"])
        end = 5 + len(report.runs)
        chart = workbook.add_chart({"type": "column"})
        chart.add_series({"name": "Overall Score", "categories": f"='Executive Summary'!$A$6:$A${end}", "values": f"='Executive Summary'!$C$6:$C${end}", "fill": {"color": TEAL}, "data_labels": {"value": True, "num_format": "0%"}})
        chart.set_title({"name": "Overall Score by Model"}); chart.set_y_axis({"min": 0, "max": 1, "num_format": "0%"}); chart.set_legend({"none": True}); chart.set_size({"width": 720, "height": 340}); chart.set_style(10)
        sheet.insert_chart("A10", chart)
        sheet.set_column("A:B", 22); sheet.set_column("C:F", 18)

    def _generic_sheet(self, workbook, sheet_name, rows, formats):
        sheet = workbook.add_worksheet(sheet_name[:31])
        sheet.hide_gridlines(2)
        columns = tuple(dict.fromkeys(key for row in rows for key in row)) or ("status",)
        for col, name in enumerate(columns): sheet.write(0, col, name.replace("_", " ").title(), formats["header"])
        for row_index, row in enumerate(rows, start=1):
            for col, name in enumerate(columns):
                value: Any = safe_cell(row.get(name, ""))
                sheet.write(row_index, col, value if value != "" else "Unavailable", formats["unavailable"] if value == "" else formats["body"])
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, max(len(rows), 1), len(columns) - 1)
        for col, name in enumerate(columns):
            width = min(52, max(14, len(name) + 2, *(len(str(row.get(name, ""))) + 2 for row in rows)))
            sheet.set_column(col, col, width)
