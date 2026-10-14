"""Readonly native-dialog SOURCE candidate. Not integrated or GUI-accepted.

Import-free view model can be checked without creating a Qt/native window.
PySide6 is imported only when the host explicitly constructs the dialog.
"""
from collections import Counter


def display_number(value, suffix=" g", language="ko"):
    return ("Unknown" if language == "en" else "미확인") if value is None else f"{value:.3f}{suffix}"


def view_model(review, language="ko"):
    c = review["coverage"]
    codes = Counter(i["code"] for i in review["issues"])
    headings = ["부품 / 포함 범위", "명목 기준", "명목 질량", "기하 추정 질량", "실측·확인 질량", "CG 상태"]
    summary = ["전체 질량·무게중심 입력 검토",
               "전체 설계 검토 · 선택 부품 검사와 별도",
               "입력 근거 선언의 검토이며 실제 검교정·제작·비행 승인이 아닙니다.",
               "실제 전체 질량: " + display_number(review["actual_complete_mass_g"]),
               "실제 전체 CG: " + ("미확인" if review["actual_complete_CG_world_mm"] is None else
                                  str(review["actual_complete_CG_world_mm"]) + " mm"),
               f"질량 owner {c['owners']}개 · 포함 child {c['covered_children']}개 · CAD 부품 {c['parts']}개",
               f"실측·확인 질량 {c['qualified_mass_owners']}/{c['owners']} · 확인된 질량 중심점 {c['qualified_CG_owners']}/{c['owners']}",
               f"추가 구성 확인 {c['resolved_additions']}/{c['required_additions']}",
               "선언 명목·설계 목표 소계: " + display_number(review["declared_nominal_subtotal_g"]),
               "균일 밀도 기하 추정 소계: " + display_number(review["geometry_density_estimate_subtotal_g"]),
               "위 두 범위의 조건부 합계: " + display_number(review["conditional_nominal_total_g"]),
               "기하 추정 범위는 실제 CG 또는 구매 제품 전체 CG 검증이 아닙니다.",
               "캐시 더미 X: " + display_number(review["cached_reference_dummy_x_mm"], " mm") +
               " · 실제 운용 더미 X: " + display_number(review["actual_operating_dummy_x_mm"], " mm"),
               "좌표계: " + str(review["coordinate_frame_id"]) + " · 실제 설치/FRD 정렬 미검증",
               "현재 상태: " + {"data_insufficient": "자료 부족", "invalid_input": "입력 오류",
                 "qualified_input_complete_not_hardware_release": "입력 선언 검토 충족 · 실측 검교정/제작/비행 승인 아님"}.get(review["status"], review["status"])]
    rows = []
    for row in review["rows"]:
        kind = {"design_target_not_measurement": "설계 목표", "declared_product_reference": "제품 명목",
                "uniform_density_geometry_estimate": "기하·균일 밀도"}.get(row["nominal_kind"], "명목")
        point_status = "실측·확인 질량 중심점" if row["actual_CG_world_mm"] is not None else "실제 CG 미확인"
        if row["geometry_frame_status"] == "inherited_nominal_proxy_frame_unproven":
            point_status += " · 이전 명목 위치, 좌표 근거 미확인"
            if row.get("inherited_reference"):
                point_status += "\n상속 참조점 " + str(row["inherited_reference"]["point_mm"]) + " mm · 표시용, 좌표계 미확인"
        elif row["geometry_frame_status"] == "proven_world_geometry":
            point_status += " · 기하 world 중심점만 확인"
        rows.append([row["label"] + " [" + row["part_id"] + "]\n" + ", ".join(row["covers"]), kind,
                     display_number(row["nominal_g"]), display_number(row["estimate_g"]),
                     display_number(row["actual_g"]), point_status])
    for child in review["covered_rows"]:
        rows.append([child["part_id"], "포함 owner: " + str(child["owner_part_id"]),
                     "별도 합산 안 함", "별도 합산 안 함", "하위 질량 미분리", "owner 전체 CG 확인 필요"])
    if language == "en":
        fmt = lambda value, suffix=" g": display_number(value, suffix, "en")
        summary = ["Whole assembly mass / CG input review", "Entire design · separate from selected-part inspection",
            "Input evidence declarations only; no physical calibration, manufacture or flight authorization.",
            "Actual complete mass: " + fmt(review["actual_complete_mass_g"]),
            "Actual complete CG: " + ("Unknown" if review["actual_complete_CG_world_mm"] is None else str(review["actual_complete_CG_world_mm"]) + " mm"),
            f"{c['owners']} mass owners · {c['covered_children']} covered children · {c['parts']} CAD parts",
            f"Qualified mass input {c['qualified_mass_owners']}/{c['owners']} · qualified mass centroid input {c['qualified_CG_owners']}/{c['owners']}",
            f"Additional scope confirmed {c['resolved_additions']}/{c['required_additions']}",
            "Declared nominal / design-target subtotal: " + fmt(review["declared_nominal_subtotal_g"]),
            "Uniform-density geometry estimate subtotal: " + fmt(review["geometry_density_estimate_subtotal_g"]),
            "Conditional sum of the above scopes: " + fmt(review["conditional_nominal_total_g"]),
            "The geometry subset is not actual or complete purchased-product CG validation.",
            "Cached dummy X: " + fmt(review["cached_reference_dummy_x_mm"], " mm") + " · actual operating dummy X: " + fmt(review["actual_operating_dummy_x_mm"], " mm"),
            "Frame: " + str(review["coordinate_frame_id"]) + " · actual installation / FRD alignment unverified",
            "Status: " + {"data_insufficient": "Data insufficient", "invalid_input": "Invalid input",
                "qualified_input_complete_not_hardware_release": "Input declarations complete · not physical calibration/manufacture/flight approval"}.get(review["status"], review["status"])]
        headings = ["Part / included scope", "Nominal basis", "Nominal mass", "Geometry estimate", "Qualified mass input", "CG status"]
        for i, row in enumerate(review["rows"]):
            rows[i][1] = {"design_target_not_measurement": "Design target", "declared_product_reference": "Product nominal",
                          "uniform_density_geometry_estimate": "Uniform-density geometry"}.get(row["nominal_kind"], "Nominal")
            rows[i][2:5] = [fmt(row["nominal_g"]), fmt(row["estimate_g"]), fmt(row["actual_g"])]
            rows[i][5] = "Qualified mass-centroid INPUT" if row["actual_CG_world_mm"] is not None else "Actual CG unknown"
            if row["geometry_frame_status"] == "inherited_nominal_proxy_frame_unproven":
                rows[i][5] += " · inherited nominal point, frame unproven"
                if row.get("inherited_reference"):
                    rows[i][5] += "\nInherited reference " + str(row["inherited_reference"]["point_mm"]) + " mm · display only, frame unknown"
            elif row["geometry_frame_status"] == "proven_world_geometry":
                rows[i][5] += " · world geometry centroid only"
        for i, child in enumerate(review["covered_rows"], len(review["rows"])):
            rows[i] = [child["part_id"], "Included owner: " + str(child["owner_part_id"]),
                       "Not added separately", "Not added separately", "Submass unallocated", "Complete owner CG required"]
    return {"summary": summary, "headings": headings, "rows": rows,
            "reasons": [f"{code}: {count}개" for code, count in sorted(codes.items())],
            "readonly": True, "kernel_calls": 0}


def make_dialog(parent, review, language="ko"):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget,
                                  QTableWidgetItem, QAbstractItemView, QDialogButtonBox)
    vm = view_model(review, language)
    dialog = QDialog(parent)
    dialog.setWindowTitle("Whole assembly mass / CG input review · read only" if language == "en" else "전체 질량·무게중심 입력 검토 · 읽기 전용")
    dialog.resize(1180, 760)
    layout = QVBoxLayout(dialog)
    label = QLabel("\n".join(vm["summary"]))
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(label)
    table = QTableWidget(len(vm["rows"]), len(vm["headings"]))
    table.setHorizontalHeaderLabels(vm["headings"])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(False)
    for i, row in enumerate(vm["rows"]):
        for j, value in enumerate(row):
            table.setItem(i, j, QTableWidgetItem(value))
    table.setColumnWidth(0, 320)
    table.setColumnWidth(1, 165)
    table.setColumnWidth(5, 360)
    layout.addWidget(table)
    reasons = QLabel(" · ".join(vm["reasons"]))
    reasons.setWordWrap(True)
    reasons.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(reasons)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog
