"""
介護報酬加算 提案アルゴリズム - コアロジック

処理フロー:
  1) 業務形態によるフィルタリング
  2) 各加算の現状ステータス判定(取得済み/即時申請可/あと一歩/要体制整備)
  3) コスト見積もり(初期・ランニング)
  4) 収益見積もり(月間・年間)
  5) 難易度スコアリング
  6) ①費用対効果ランキング / ④獲得容易性ランキング の生成
  7) ③ロードマップ(要件クリア手順+現行システム対応可否)の生成
  8) レポート組み立て
"""

from dataclasses import dataclass, field
from models import BillingBasis, FacilityProfile, KasanDefinition


# ---------------------------------------------------------------------------
# 出力データ構造
# ---------------------------------------------------------------------------
@dataclass
class KasanEvaluation:
    kasan: KasanDefinition
    status: str                     # "取得済み" / "即時申請可能" / "あと一歩" / "要体制整備"
    unmet_requirements: list        # list[Requirement]
    target_user_count: int
    monthly_revenue_yen: float
    annual_revenue_yen: float
    initial_cost_yen: float
    annual_running_cost_yen: float
    net_annual_benefit_yen: float   # 年間収益 - 年間ランニングコスト - 初期コスト(初年度按分)
    difficulty_score: float         # 低いほど容易
    difficulty_label: str
    roadmap: list                   # list[str]
    system_advice: str


@dataclass
class Report:
    profile: FacilityProfile
    all_evaluations: list                 # list[KasanEvaluation] (取得済み含む全件)
    top_cost_effective: list              # ①費用対効果ランキング(黒字のみ、上位)
    negative_roi_examples: list           # 参考: 赤字が見込まれる加算(現実的アドバイス用)
    top_easy_to_acquire: list             # ④獲得容易性ランキング(上位)


# ---------------------------------------------------------------------------
# ステップ1: 業務形態によるフィルタリング
# ---------------------------------------------------------------------------
def filter_by_service_category(master: list, profile: FacilityProfile) -> list:
    candidates = []
    for k in master:
        if profile.service_category not in k.service_categories:
            continue
        if k.service_types and profile.service_type not in k.service_types:
            continue
        candidates.append(k)
    return candidates


# ---------------------------------------------------------------------------
# ステップ2: ステータス判定
# ---------------------------------------------------------------------------
def classify_status(k: KasanDefinition, profile: FacilityProfile):
    unmet = [r for r in k.requirements if not r.check(profile)]
    if k.code in profile.current_status.acquired:
        return "取得済み", unmet
    if not unmet:
        return "即時申請可能(要件充足)", unmet
    if k.code in profile.current_status.near_acquisition:
        return "あと一歩(要件を一部未充足)", unmet
    # 未充足要件の割合で判定
    unmet_ratio = len(unmet) / max(len(k.requirements), 1)
    if unmet_ratio <= 0.34:
        return "あと一歩(要件を一部未充足)", unmet
    return "要体制整備", unmet


# ---------------------------------------------------------------------------
# ステップ3: コスト見積もり
# ---------------------------------------------------------------------------
def estimate_initial_cost(k: KasanDefinition, profile: FacilityProfile) -> float:
    total = 0.0
    for fn in k.initial_cost_items:
        item = fn(profile)
        if item is not None:
            total += item.amount_yen
    return total


def estimate_annual_running_cost(k: KasanDefinition, profile: FacilityProfile) -> float:
    total = 0.0
    for fn in k.running_cost_items:
        item = fn(profile)
        if item is not None:
            total += item.amount_yen
    return total


# ---------------------------------------------------------------------------
# ステップ4: 収益見積もり
# ---------------------------------------------------------------------------
def estimate_monthly_revenue(k: KasanDefinition, profile: FacilityProfile) -> float:
    target_n = k.target_user_selector(profile.users)

    if k.billing_basis == BillingBasis.PER_USER_PER_DAY:
        return k.unit_points * profile.point_value_yen * target_n * profile.service_days_per_month

    if k.billing_basis == BillingBasis.PER_USER_PER_MONTH:
        return k.unit_points * profile.point_value_yen * target_n

    if k.billing_basis == BillingBasis.FACILITY_PER_MONTH:
        return k.unit_points * profile.point_value_yen

    if k.billing_basis == BillingBasis.PER_VISIT:
        visits_per_month = target_n  # target_user_selectorに月間想定回数を持たせる設計
        return k.unit_points * profile.point_value_yen * visits_per_month

    if k.billing_basis == BillingBasis.PERCENTAGE_OF_BILLING:
        return profile.base_monthly_billing_yen * (k.unit_points / 100.0)

    raise ValueError(f"unknown billing_basis: {k.billing_basis}")


# ---------------------------------------------------------------------------
# ステップ5: 難易度スコアリング (低いほど「取りやすい」)
# ---------------------------------------------------------------------------
def compute_difficulty_score(k: KasanDefinition, unmet_ratio: float) -> float:
    d = k.difficulty
    score = 0.0
    score += 30 if d.staff_change_required else 0
    score += 20 if d.system_change_required else 0
    score += d.documentation_load * 6       # 最大30
    score += d.lead_time_months * 4         # 目安: 半年で24点
    score += unmet_ratio * 20               # 最大20
    return round(score, 1)


def difficulty_label(score: float) -> str:
    if score <= 15:
        return "即時対応可(書類・運用の微調整のみ)"
    if score <= 40:
        return "軽微な体制整備で対応可"
    if score <= 70:
        return "中程度の体制整備が必要"
    return "大幅な体制整備・新規採用が必要"


# ---------------------------------------------------------------------------
# ステップ7: ロードマップ生成
# ---------------------------------------------------------------------------
def build_roadmap(k: KasanDefinition, profile: FacilityProfile, unmet) -> list:
    steps = []
    for r in unmet:
        steps.append(f"[要件充足] {r.description}")
    steps.extend(k.roadmap_template)
    return steps


def build_system_advice(k: KasanDefinition, profile: FacilityProfile) -> str:
    compat = k.system_compatibility.get(profile.current_system, "未登録システムのため個別確認が必要")
    return f"現行システム『{profile.current_system}』: {compat}"


# ---------------------------------------------------------------------------
# メイン: 加算の評価
# ---------------------------------------------------------------------------
def evaluate_kasan(k: KasanDefinition, profile: FacilityProfile) -> KasanEvaluation:
    status, unmet = classify_status(k, profile)
    unmet_ratio = len(unmet) / max(len(k.requirements), 1)

    target_n = k.target_user_selector(profile.users)
    monthly_revenue = estimate_monthly_revenue(k, profile)
    annual_revenue = monthly_revenue * 12

    initial_cost = estimate_initial_cost(k, profile)
    annual_running_cost = estimate_annual_running_cost(k, profile)

    # 初年度は初期コストを全額計上する単純化したモデル(=保守的な見積もり)
    net_annual_benefit = annual_revenue - annual_running_cost - initial_cost

    score = compute_difficulty_score(k, unmet_ratio)

    return KasanEvaluation(
        kasan=k,
        status=status,
        unmet_requirements=unmet,
        target_user_count=target_n,
        monthly_revenue_yen=round(monthly_revenue),
        annual_revenue_yen=round(annual_revenue),
        initial_cost_yen=round(initial_cost),
        annual_running_cost_yen=round(annual_running_cost),
        net_annual_benefit_yen=round(net_annual_benefit),
        difficulty_score=score,
        difficulty_label=difficulty_label(score),
        roadmap=build_roadmap(k, profile, unmet),
        system_advice=build_system_advice(k, profile),
    )


# ---------------------------------------------------------------------------
# メイン: レポート生成
# ---------------------------------------------------------------------------
def analyze(master: list, profile: FacilityProfile, top_n: int = 5) -> Report:
    candidates = filter_by_service_category(master, profile)
    evaluations = [evaluate_kasan(k, profile) for k in candidates]

    unacquired = [e for e in evaluations if e.status != "取得済み"]

    positive = [e for e in unacquired if e.net_annual_benefit_yen > 0]
    negative = [e for e in unacquired if e.net_annual_benefit_yen <= 0]

    top_cost_effective = sorted(positive, key=lambda e: e.net_annual_benefit_yen, reverse=True)[:top_n]
    negative_roi_examples = sorted(negative, key=lambda e: e.net_annual_benefit_yen)[:top_n]

    top_easy_to_acquire = sorted(unacquired, key=lambda e: e.difficulty_score)[:top_n]

    return Report(
        profile=profile,
        all_evaluations=evaluations,
        top_cost_effective=top_cost_effective,
        negative_roi_examples=negative_roi_examples,
        top_easy_to_acquire=top_easy_to_acquire,
    )


# ---------------------------------------------------------------------------
# レポート表示用ヘルパー
# ---------------------------------------------------------------------------
def format_evaluation(e: KasanEvaluation, rank: int = None) -> str:
    lines = []
    prefix = f"[{rank}位] " if rank else ""
    lines.append(f"{prefix}{e.kasan.name} ({e.kasan.code})")
    lines.append(f"  ステータス: {e.status}")
    lines.append(f"  対象者数: {e.target_user_count}人 / 月間収益(概算): {e.monthly_revenue_yen:,}円 / 年間収益(概算): {e.annual_revenue_yen:,}円")
    lines.append(f"  初期コスト: {e.initial_cost_yen:,}円 / 年間ランニングコスト: {e.annual_running_cost_yen:,}円")
    lines.append(f"  初年度 純損益(概算): {e.net_annual_benefit_yen:,}円")
    lines.append(f"  難易度スコア: {e.difficulty_score} ({e.difficulty_label})")
    lines.append(f"  {e.system_advice}")
    if e.roadmap:
        lines.append("  ロードマップ:")
        for i, step in enumerate(e.roadmap, 1):
            lines.append(f"    {i}. {step}")
    if e.kasan.notes:
        lines.append(f"  備考: {e.kasan.notes}")
    return "\n".join(lines)
