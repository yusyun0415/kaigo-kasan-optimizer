# -*- coding: utf-8 -*-
"""
デモ: 2つの施設プロファイルでアルゴリズムを実行し、出力①②③④を確認する。

  例1: 通所介護(中規模、PT配置済・管理栄養士未配置) -> 黒字/赤字が混在するケース
  例2: 特別養護老人ホーム(小規模、管理栄養士未配置) -> 明確な赤字例(要求仕様3.への対応確認)
"""

from models import (
    ServiceCategory, StaffInfo, UserComposition, CurrentStatus, FacilityProfile,
)
from kasan_master import ALL_KASAN
from advisor import analyze, format_evaluation


def print_report(title: str, report):
    print("=" * 70)
    print(title)
    print("=" * 70)

    print("\n--- ① 費用対効果が高い加算ランキング(Top) ---")
    if not report.top_cost_effective:
        print("  該当なし")
    for i, e in enumerate(report.top_cost_effective, 1):
        print(format_evaluation(e, i))
        print()

    print("--- ④ 獲得しやすい(難易度が低い)加算ランキング(Top) ---")
    for i, e in enumerate(report.top_easy_to_acquire, 1):
        print(format_evaluation(e, i))
        print()

    print("--- 参考: 費用対効果がマイナスと見込まれる加算(現実的アドバイス) ---")
    if not report.negative_roi_examples:
        print("  該当なし")
    for e in report.negative_roi_examples:
        print(format_evaluation(e))
        print()


# ---------------------------------------------------------------------------
# 例1: 通所介護
# ---------------------------------------------------------------------------
profile_daycare = FacilityProfile(
    service_category=ServiceCategory.DAYCARE,
    service_type="通所介護",
    staff=StaffInfo(
        care_workers_ftk=8.0,
        nurses_ftk=1.0,
        dietitian_count=0,
        dietitian_external_partnership=False,
        rehab_staff_count=1,          # PTを1名配置済み
        care_manager_count=1,
        care_worker_certified_ratio=0.4,
    ),
    users=UserComposition(
        support_level_counts={1: 5, 2: 8},
        care_level_counts={1: 10, 2: 12, 3: 8, 4: 5, 5: 2},
        dementia_high_ratio=0.3,
        medical_dependency_ratio=0.05,
    ),
    current_status=CurrentStatus(
        acquired={"ORAL_NUTRITION_SCREENING_1"},
        near_acquisition={"NUTRITION_ASSESS"},
    ),
    current_system="カイポケ",
    point_value_yen=10.00,
    service_days_per_month=22,
    base_monthly_billing_yen=6_000_000,
)

report1 = analyze(ALL_KASAN, profile_daycare)
print_report("例1: 通所介護(中規模・PT配置済/管理栄養士未配置)", report1)


# ---------------------------------------------------------------------------
# 例2: 特別養護老人ホーム(小規模) - 赤字例の確認
# ---------------------------------------------------------------------------
profile_facility = FacilityProfile(
    service_category=ServiceCategory.FACILITY,
    service_type="特別養護老人ホーム",
    staff=StaffInfo(
        care_workers_ftk=15.0,
        nurses_ftk=2.0,
        dietitian_count=0,             # 管理栄養士 未配置
        rehab_staff_count=0,
        care_manager_count=1,
    ),
    users=UserComposition(
        support_level_counts={},
        care_level_counts={1: 2, 2: 5, 3: 8, 4: 7, 5: 3},  # 合計25人
        dementia_high_ratio=0.6,
        medical_dependency_ratio=0.1,
    ),
    current_status=CurrentStatus(acquired=set(), near_acquisition=set()),
    current_system="ワイズマン",
    point_value_yen=10.90,
    service_days_per_month=30,  # 入所系は毎日算定対象
    base_monthly_billing_yen=8_000_000,
)

report2 = analyze(ALL_KASAN, profile_facility)
print_report("例2: 特別養護老人ホーム(小規模・管理栄養士未配置)", report2)

print("=" * 70)
print("例2 個別確認: 栄養マネジメント強化加算(管理栄養士 新規雇用ケース)")
print("=" * 70)
nutrition_eval = next(e for e in report2.all_evaluations if e.kasan.code == "NUTRITION_MGMT_STRENGTH")
print(format_evaluation(nutrition_eval))
print()
print(
    f">>> 年間加算収益(概算) {nutrition_eval.annual_revenue_yen:,}円 に対し、"
    f"管理栄養士 新規雇用の年間人件費 {nutrition_eval.annual_running_cost_yen:,}円 + "
    f"初期採用費 {nutrition_eval.initial_cost_yen:,}円 がかかるため、"
    f"初年度収支は {nutrition_eval.net_annual_benefit_yen:,}円 の赤字が見込まれる。"
)
