"""
介護報酬加算 最適化提案エンジン - 参照実装
=========================================

設計方針
--------
1. 「加算マスタ」を業務ロジックから完全分離する。
   単位数・算定要件は3年ごとの報酬改定（直近: 令和6年度=2024年度改定）や
   毎年の処遇改善加算の運用見直しで変わるため、コード変更なしに
   マスタ(JSON/DB)だけ更新すれば追随できる構造にする。
2. このファイルの ADDON_MASTER は「代表例」であり全加算網羅ではない。
   実運用では公式告示・通知に基づき全サービス種別・全加算をマスタ化すること。
3. 単位数(unit_value)は令和6年度改定時点の代表値。地域区分による
   1単位あたり単価(10.00円~11.40円)は REGION_UNIT_PRICE で調整する。
   本番投入前に最新の告示単価表で検証すること。
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 0. マスタ定数
# ---------------------------------------------------------------------------

# 地域区分ごとの1単位あたり単価（円）。サービス種別により係数はやや異なるが
# ここでは簡略化して代表値を採用。本番では区分×サービス種別の単価表を使う。
REGION_UNIT_PRICE = {
    "1級地": 11.40,
    "2級地": 11.12,
    "3級地": 11.05,
    "4級地": 10.84,
    "5級地": 10.70,
    "6級地": 10.42,
    "7級地": 10.21,
    "その他": 10.00,
}

# 現行主要システムのLIFE連携（科学的介護推進体制加算等で必須のCSV提出）対応度。
# 1.0 = ほぼ自動連携、0.5 = エクスポート対応だが手作業変換が必要、0.0 = 個別対応要
CARE_SOFTWARE_LIFE_SUPPORT = {
    "カイポケ": 0.8,
    "ワイズマン": 0.9,
    "ほのぼの": 0.8,
    "ケアカルテ": 0.7,
    "その他": 0.3,
}


@dataclass
class StaffInfo:
    care_worker_ftv: float  # 介護職員 常勤換算数
    nurse_count: float = 0
    dietitian_count: float = 0
    rehab_staff_count: float = 0  # PT/OT/ST 常勤換算合計
    care_manager_count: float = 0
    trained_dementia_staff: int = 0  # 認知症介護実践者研修修了者数など


@dataclass
class UserComposition:
    support1: int = 0
    support2: int = 0
    care1: int = 0
    care2: int = 0
    care3: int = 0
    care4: int = 0
    care5: int = 0
    dementia_ratio: float = 0.0  # 認知症日常生活自立度III以上の割合
    high_medical_need_ratio: float = 0.0

    @property
    def total_users(self) -> int:
        return (self.support1 + self.support2 + self.care1 + self.care2
                + self.care3 + self.care4 + self.care5)

    @property
    def total_care_only(self) -> int:  # 要介護のみ（要支援除く）
        return self.care1 + self.care2 + self.care3 + self.care4 + self.care5

    @property
    def mid_to_high_care_ratio(self) -> float:
        """中重度者(要介護3以上)の割合。中重度者ケア体制加算等の判定に使用。"""
        denom = self.total_care_only
        if denom == 0:
            return 0.0
        return (self.care3 + self.care4 + self.care5) / denom


@dataclass
class FacilityInput:
    service_type: str  # 例: "通所介護", "訪問介護", "訪問看護", "特別養護老人ホーム", "介護老人保健施設"
    staff: StaffInfo
    users: UserComposition
    current_addons: set = field(default_factory=set)   # 取得済み加算コード
    near_miss_addons: set = field(default_factory=set)  # 要件をほぼ満たしている加算コード（自己申告）
    care_software: str = "その他"
    region_class: str = "その他"

    @property
    def unit_price(self) -> float:
        return REGION_UNIT_PRICE.get(self.region_class, 10.00)


@dataclass
class AddonMaster:
    code: str
    name: str
    applicable_services: list
    unit_value: float          # 単位数（参考値。要最新確認）
    billing_basis: str         # "per_visit" | "per_month" | "per_day"
    monthly_frequency: float   # 想定算定回数/月（billing_basisがper_visit/per_dayの場合の目安）
    requirement_staff: dict    # 例: {"rehab_staff_count": 1} 不足していれば要採用
    requirement_process: list  # 運用上必要な手続き（書類・アセスメント頻度等）
    requires_life_submission: bool = False  # LIFEへのデータ提出が必須か
    hiring_needed_role: Optional[str] = None      # 新規雇用が必要な場合の職種名
    hiring_annual_cost: float = 0.0               # 新規雇用した場合の年間人件費目安（円）
    training_annual_cost: float = 0.0             # 研修費用の年間目安（円）
    system_initial_cost: float = 0.0              # システム導入・改修初期費用目安（円）
    notes: str = ""


# ---------------------------------------------------------------------------
# 1. 加算マスタ（代表例。実運用では全加算を網羅したDB/JSONに置き換える）
# ---------------------------------------------------------------------------

ADDON_MASTER = [
    AddonMaster(
        code="LIFE_KAGAKUTEKI",
        name="科学的介護推進体制加算(I)",
        applicable_services=["通所介護", "訪問看護", "特別養護老人ホーム",
                              "介護老人保健施設", "通所リハビリテーション"],
        unit_value=40, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=["利用者ごとのADL・栄養・口腔等の情報をLIFEへ提出",
                              "フィードバックを踏まえたケア計画の見直し(PDCA)"],
        requires_life_submission=True,
        system_initial_cost=0, training_annual_cost=50000,
        notes="人員要件なし。既存ソフトのLIFE連携機能があれば追加投資はほぼ不要。",
    ),
    AddonMaster(
        code="KOBETSU_KINOU_I",
        name="個別機能訓練加算(I)ロ",
        applicable_services=["通所介護"],
        unit_value=56, billing_basis="per_visit", monthly_frequency=22,
        requirement_staff={"rehab_staff_count": 1},
        requirement_process=["個別機能訓練計画書の作成", "3ヶ月ごとの評価・見直し",
                              "生活機能向上を目的とした訓練の実施記録"],
        hiring_needed_role="機能訓練指導員(PT/OT/ST等)",
        hiring_annual_cost=4200000, training_annual_cost=0,
        notes="専従1名(非常勤可)配置で算定可。常勤専従化で(II)への上位も検討可。",
    ),
    AddonMaster(
        code="KOUKUEIYOU_SCREEN",
        name="口腔・栄養スクリーニング加算(I)",
        applicable_services=["通所介護", "通所リハビリテーション"],
        unit_value=20, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=["6ヶ月に1回、口腔・栄養状態のスクリーニングを実施し記録",
                              "居宅介護支援事業所への情報提供"],
        notes="人員要件なし。既存職員での実施が可能なため難易度は低い。",
    ),
    AddonMaster(
        code="EIYOU_ASSESSMENT",
        name="栄養アセスメント加算",
        applicable_services=["通所介護", "通所リハビリテーション",
                              "特別養護老人ホーム", "介護老人保健施設"],
        unit_value=50, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"dietitian_count": 1},
        requirement_process=["管理栄養士による栄養アセスメントの実施(利用開始時・3ヶ月毎)",
                              "多職種連携での栄養ケア計画作成"],
        hiring_needed_role="管理栄養士",
        hiring_annual_cost=4500000,
        notes="他事業所との連携(栄養士外部委託・巡回)で常勤雇用を回避できる場合あり。",
    ),
    AddonMaster(
        code="NINCHISHOU_SENMON_I",
        name="認知症専門ケア加算(I)",
        applicable_services=["通所介護", "訪問介護", "特別養護老人ホーム",
                              "介護老人保健施設", "グループホーム"],
        unit_value=3, billing_basis="per_day", monthly_frequency=22,
        requirement_staff={"trained_dementia_staff": 1},
        requirement_process=["認知症日常生活自立度III以上の利用者が利用者の半数以上",
                              "認知症介護実践リーダー研修修了者の配置",
                              "認知症ケアに関する会議を定期開催"],
        training_annual_cost=150000,
        notes="対象者割合(認知症III以上が全体の1/2以上)を満たすかが最大の分岐点。",
    ),
    AddonMaster(
        code="SEISAN_TEISEI_KYOKA",
        name="サービス提供体制強化加算(I)",
        applicable_services=["通所介護", "訪問介護", "訪問看護",
                              "特別養護老人ホーム", "介護老人保健施設"],
        unit_value=22, billing_basis="per_visit", monthly_frequency=22,
        requirement_staff={},
        requirement_process=["介護福祉士の割合が利用者に対し一定割合以上(サービス種別ごとに規定)",
                              "職員研修計画の策定・実施", "会議の定期開催"],
        notes="有資格者比率が既に高い事業所は追加投資ゼロで即算定可能な典型例。",
    ),
    AddonMaster(
        code="SEIKATSU_KINOU_RENKEI",
        name="生活機能向上連携加算(I)",
        applicable_services=["通所介護", "訪問介護"],
        unit_value=100, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=["外部のリハ専門職(訪問リハ事業所等)と連携しアセスメント",
                              "個別サービス計画への反映"],
        notes="自前でPT/OT/ST雇用不要。外部連携のみで算定可能な低コスト加算。",
    ),
    AddonMaster(
        code="NYUYOKU_KAIJO_II",
        name="入浴介助加算(II)",
        applicable_services=["通所介護"],
        unit_value=55, billing_basis="per_visit", monthly_frequency=18,
        requirement_staff={"rehab_staff_count": 0.1},
        requirement_process=["利用者の居宅を訪問し浴室環境等をアセスメント",
                              "個浴等、居宅の状況に近い環境での入浴介助計画作成"],
        notes="訪問アセスメントの運用構築が主な負荷。人員新規雇用は不要な場合が多い。",
    ),
    AddonMaster(
        code="TOKUTEI_JIGYOSHO_I",
        name="特定事業所加算(I)",
        applicable_services=["訪問介護"],
        # 本来は「総単位数×20%」の加算率型だが、本サンプルでは基本報酬の総額を
        # 入力に持たないため、訪問1回あたりの想定加算額に単純換算した代表値を用いる。
        # 実運用では「事業所の月間総単位数×加算率」で計算するロジックに置き換えること。
        unit_value=190, billing_basis="per_visit", monthly_frequency=25,
        requirement_staff={"care_worker_ftv": 0},
        requirement_process=["訪問介護員等の計画的な研修実施", "会議の定期開催(月1回以上)",
                              "重度要介護者等対応要件を満たす", "サービス提供責任者の要件充足"],
        notes="加算率(総単位数の20%)型。人員要件・研修体制が整っていれば追加雇用なしで高収益。",
    ),
    AddonMaster(
        code="KANKYU_HOMON_KANGO",
        name="緊急時訪問看護加算",
        applicable_services=["訪問看護"],
        unit_value=574, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"nurse_count": 1},
        requirement_process=["24時間連絡体制の確保", "利用者への説明・同意取得"],
        hiring_needed_role="オンコール体制強化のための看護師増員(場合による)",
        hiring_annual_cost=0,
        notes="既存看護師でオンコール体制を組める場合は追加人件費なしで算定可。",
    ),
    AddonMaster(
        code="NICHIJO_KEIZOKU",
        name="日常生活継続支援加算",
        applicable_services=["特別養護老人ホーム"],
        unit_value=36, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={"care_worker_ftv": 0},
        requirement_process=["要介護4・5の入所者割合が7割以上",
                              "介護福祉士の配置割合要件(6割以上等)を充足"],
        notes="重度者割合と介護福祉士比率の2条件。人員要件充足がボトルネックになりやすい。",
    ),
    AddonMaster(
        code="HAISETSU_SHIEN",
        name="排せつ支援加算(I)",
        applicable_services=["特別養護老人ホーム", "介護老人保健施設"],
        unit_value=10, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=["医師・看護師・介護支援専門員等が排せつ状態を評価",
                              "支援計画作成と3ヶ月ごとの見直し", "LIFEへの提出"],
        requires_life_submission=True,
        notes="多職種評価さえ運用化できれば追加投資は小さい。",
    ),
]


# ---------------------------------------------------------------------------
# 2. コアアルゴリズム
# ---------------------------------------------------------------------------

def filter_by_service(facility: FacilityInput) -> list:
    """STEP0: 業務形態に存在しない加算を除外する。"""
    return [a for a in ADDON_MASTER if facility.service_type in a.applicable_services]


def compute_requirement_gap(facility: FacilityInput, addon: AddonMaster) -> dict:
    """STEP1: 現状の人員・利用者構成と加算要件の差分(ギャップ)を計算する。

    戻り値の各キーはギャップの種類。値が0なら要件を満たしている。
    """
    staff = facility.staff
    gap = {"staffing_gap": 0.0, "process_gap": 0, "system_gap": 0.0}

    for role, required in addon.requirement_staff.items():
        current = getattr(staff, role, 0)
        if current < required:
            gap["staffing_gap"] += (required - current)

    # 書類・運用手続きは「未整備なら1件ごとに1ポイント」という単純化した扱い。
    # 実運用では事業所への現況ヒアリング結果を反映するのが望ましい。
    gap["process_gap"] = len(addon.requirement_process)

    if addon.requires_life_submission:
        life_support = CARE_SOFTWARE_LIFE_SUPPORT.get(facility.care_software, 0.3)
        gap["system_gap"] = round((1 - life_support), 2)

    return gap


def estimate_annual_revenue(facility: FacilityInput, addon: AddonMaster) -> float:
    """STEP2: 加算による想定年間請求増加額を算出する。

    対象利用者数は加算の性質に応じて概算する。日常的な人員配置加算・体制加算は
    利用者全員が対象、個別評価系(認知症専門ケア等)は該当割合のみを対象とする、
    という簡略ルールを採用。より精緻にはaddonごとに対象者算出関数を持たせる。
    """
    total_users = facility.users.total_users or 1

    if addon.code == "NINCHISHOU_SENMON_I":
        eligible = total_users * facility.users.dementia_ratio
    elif addon.code == "NICHIJO_KEIZOKU":
        eligible = facility.users.care4 + facility.users.care5
    else:
        eligible = total_users

    monthly_units = addon.unit_value * addon.monthly_frequency * eligible
    monthly_yen = monthly_units * facility.unit_price
    return round(monthly_yen * 12, 0)


def estimate_annual_cost(facility: FacilityInput, addon: AddonMaster, gap: dict) -> dict:
    """STEP3: 初期コストとランニングコストを見積もる。

    人員ギャップが実在する場合のみ雇用コストを計上する
    (既に要件を満たしている場合は追加費用なしと判定するのが公正のため)。
    """
    running_cost = 0.0
    initial_cost = addon.system_initial_cost

    if gap["staffing_gap"] > 0 and addon.hiring_needed_role:
        running_cost += addon.hiring_annual_cost * min(gap["staffing_gap"], 1.0)

    running_cost += addon.training_annual_cost

    if gap["system_gap"] > 0:
        running_cost += gap["system_gap"] * 100000  # LIFE非対応度に応じた運用工数の概算換算

    return {"initial_cost": initial_cost, "running_cost_annual": running_cost}


def compute_difficulty_score(gap: dict) -> float:
    """STEP5: 難易度スコア。値が小さいほど「獲得しやすい」。

    重み付けの根拠: 人員採用は解消に数ヶ月〜半年を要し裁量の余地が小さいため最重視。
    システム対応は運用でカバーできる余地があるため中程度。書類・運用整備は
    最も裁量で解消しやすいため最も軽い重みとする。
    """
    return (gap["staffing_gap"] * 10.0
            + gap["system_gap"] * 3.0
            + gap["process_gap"] * 1.0)


def generate_roadmap(facility: FacilityInput, addon: AddonMaster, gap: dict) -> list:
    """STEP6: 要件クリアへのロードマップを順序立てて生成する。"""
    steps = []
    step_no = 1

    if gap["staffing_gap"] > 0:
        steps.append(f"{step_no}. 【人員】{addon.hiring_needed_role or '必要職種'}を"
                      f"常勤換算 {gap['staffing_gap']:.2f} 名相当、新規雇用または外部連携で確保する。")
        step_no += 1

    for process in addon.requirement_process:
        steps.append(f"{step_no}. 【運用】{process}")
        step_no += 1

    if addon.requires_life_submission:
        life_support = CARE_SOFTWARE_LIFE_SUPPORT.get(facility.care_software, 0.3)
        if life_support >= 0.8:
            sys_note = (f"{facility.care_software}はLIFE連携機能を標準搭載しているため、"
                        f"CSVエクスポート機能を有効化し運用フローに組み込むだけで対応可能。")
        elif life_support >= 0.5:
            sys_note = (f"{facility.care_software}はエクスポート対応済みだが、項目マッピングの"
                        f"手動調整が必要。導入時に代理店へ設定支援を依頼することを推奨。")
        else:
            sys_note = (f"{facility.care_software}は現状LIFE連携が弱いため、"
                        f"LIFE専用の入力補助ツール導入または手入力運用の検討が必要。")
        steps.append(f"{step_no}. 【システム】{sys_note}")
        step_no += 1

    steps.append(f"{step_no}. 【提出】都道府県・市町村へ加算算定に係る体制等状況一覧表を提出する。")
    return steps


@dataclass
class AddonResult:
    addon: AddonMaster
    gap: dict
    annual_revenue: float
    initial_cost: float
    running_cost_annual: float
    net_annual_profit: float
    difficulty_score: float
    roadmap: list


def analyze(facility: FacilityInput) -> list:
    candidates = filter_by_service(facility)
    results = []

    for addon in candidates:
        if addon.code in facility.current_addons:
            continue  # 取得済みは提案対象外

        gap = compute_requirement_gap(facility, addon)
        if addon.code in facility.near_miss_addons:
            # 自己申告で「ほぼ満たしている」場合はギャップを軽減する
            gap["process_gap"] = max(0, gap["process_gap"] - 1)

        revenue = estimate_annual_revenue(facility, addon)
        cost = estimate_annual_cost(facility, addon, gap)
        amortized_initial = cost["initial_cost"] / 5  # 初期投資を5年償却で年換算
        net_profit = revenue - cost["running_cost_annual"] - amortized_initial
        difficulty = compute_difficulty_score(gap)
        roadmap = generate_roadmap(facility, addon, gap)

        results.append(AddonResult(
            addon=addon, gap=gap, annual_revenue=revenue,
            initial_cost=cost["initial_cost"],
            running_cost_annual=cost["running_cost_annual"],
            net_annual_profit=net_profit, difficulty_score=difficulty,
            roadmap=roadmap,
        ))

    return results


def build_report(facility: FacilityInput, top_n: int = 5) -> dict:
    """4つの出力(①②③④)をまとめて生成する。"""
    results = analyze(facility)

    cost_effectiveness_rank = sorted(results, key=lambda r: r.net_annual_profit, reverse=True)[:top_n]

    # ④は「追加投資・人員変更がほぼ不要」なものを優先するため、
    # staffing_gap==0 の候補に絞った上で難易度スコア昇順に並べる。
    easy_candidates = [r for r in results if r.gap["staffing_gap"] == 0]
    ease_rank = sorted(easy_candidates, key=lambda r: r.difficulty_score)[:top_n]

    return {
        "① 費用対効果ランキング": [
            {
                "加算名": r.addon.name,
                "年間増収見込み": f"{r.annual_revenue:,.0f}円",
                "年間追加コスト": f"{(r.running_cost_annual + r.initial_cost/5):,.0f}円",
                "年間純利益": f"{r.net_annual_profit:,.0f}円",
                "赤字警告": r.net_annual_profit < 0,
            } for r in cost_effectiveness_rank
        ],
        "② コスト見積もり": [
            {
                "加算名": r.addon.name,
                "初期コスト": f"{r.initial_cost:,.0f}円",
                "ランニングコスト(年間)": f"{r.running_cost_annual:,.0f}円",
            } for r in results
        ],
        "③ 獲得ロードマップ": [
            {"加算名": r.addon.name, "手順": r.roadmap} for r in cost_effectiveness_rank
        ],
        "④ 難易度が低い加算ランキング": [
            {
                "加算名": r.addon.name,
                "難易度スコア": round(r.difficulty_score, 1),
                "年間純利益": f"{r.net_annual_profit:,.0f}円",
            } for r in ease_rank
        ],
    }


# ---------------------------------------------------------------------------
# 3. デモ実行
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    sample_facility = FacilityInput(
        service_type="通所介護",
        staff=StaffInfo(care_worker_ftv=6.0, nurse_count=1, dietitian_count=0,
                         rehab_staff_count=0, care_manager_count=1,
                         trained_dementia_staff=1),
        users=UserComposition(support1=5, support2=8, care1=10, care2=12,
                               care3=6, care4=3, care5=1,
                               dementia_ratio=0.35, high_medical_need_ratio=0.05),
        current_addons={"SEISAN_TEISEI_KYOKA"},
        near_miss_addons={"KOUKUEIYOU_SCREEN"},
        care_software="カイポケ",
        region_class="2級地",
    )

    report = build_report(sample_facility)
    print(json.dumps(report, ensure_ascii=False, indent=2))
