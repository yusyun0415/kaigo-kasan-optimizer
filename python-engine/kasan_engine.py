"""
介護報酬加算 最適化提案エンジン - 参照実装 (v2)
=========================================

v2での変更点
------------
1. コスト計算に「既存職員の稼働時間(人件費)」「水道代・光熱費」「消耗品費」を
   variable_cost_items として明示的に組み込んだ。v1では「新規雇用が必要か」しか
   見ておらず、既存職員が対応できる加算のランニングコストが0円になっていたが、
   実際には既存職員の稼働時間にも人件費が発生し、入浴介助のような加算では
   水道代・消耗品費も発生するため、これらを費目ごとに算出するようにした。
2. ロードマップをフェーズ構造(人員体制→運用ルール→システム対応→届出)に
   再編し、各運用タスクに担当者・実施頻度・作成する記録物を明示した。

設計方針(v1から継続)
--------
1. 「加算マスタ」を業務ロジックから完全分離する。
   単位数・算定要件は3年ごとの報酬改定（直近: 令和6年度=2024年度改定）や
   毎年の処遇改善加算の運用見直しで変わるため、コード変更なしに
   マスタ(JSON/DB)だけ更新すれば追随できる構造にする。
2. このファイルの ADDON_MASTER は「代表例」であり全加算網羅ではない。
   実運用では公式告示・通知に基づき全サービス種別・全加算をマスタ化すること。
3. 単位数(unit_value)・人件費単価・水道代等は令和6年度改定時点を想定した
   代表値。地域区分による1単位あたり単価(10.00円~11.40円)は
   REGION_UNIT_PRICE で調整する。本番投入前に最新の告示単価表・
   自事業所の実際の人件費率で検証すること。
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

# 費用計算に用いる標準時給(円)。あくまで代表値であり、事業所の実際の人件費率に
# 差し替えて使うこと。労務費(社会保険料等の法定福利費込み)を想定した実効時給。
STANDARD_HOURLY_WAGE = 1800


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
    requirement_process: list  # 運用上必要な手続き。各要素は下記スキーマの辞書:
                                #   {"task":内容, "owner":担当, "frequency":実施頻度, "deliverable":作成物}
    variable_cost_items: list = field(default_factory=list)
                                # 既存職員の稼働時間・水道代・消耗品等のランニングコスト。各要素:
                                #   {"label":費目名, "basis":"per_occurrence"|"per_month", "yen":単価(円)}
                                #   per_occurrence は算定1回ごと(月間算定回数×対象者数)に発生するコスト、
                                #   per_month は対象者数に関わらず月一定額発生するコスト。
    requires_life_submission: bool = False  # LIFEへのデータ提出が必須か
    hiring_needed_role: Optional[str] = None      # 新規雇用が必要な場合の職種名
    hiring_annual_cost: float = 0.0               # 新規雇用した場合の年間人件費目安（円）
    training_annual_cost: float = 0.0             # 研修費用の年間目安（円）
    system_initial_cost: float = 0.0              # システム導入・改修初期費用目安（円）
    staffing_lead_time: str = ""                  # 人員ギャップ解消の目安リードタイム(表示用)
    eligible_rule: str = "all"                    # 対象利用者数の算出ルール(下記参照)
    major: bool = False                           # True: 入力画面の「取得状況」チェックリストに表示する主要加算
    notes: str = ""


# 対象利用者数の算出ルール。"すべての加算"を対象にするため、加算コードごとの
# 個別ifではなく、入力データ(UserComposition)から機械的に人数を導けるルールに
# 一般化している。
#   all        : 利用者全員
#   dementia   : 利用者全員 × 認知症自立度III以上の割合
#   medical    : 利用者全員 × 医療依存度が高い利用者の割合
#   midHighCare: 要介護3+4+5の人数
#   heavyCare  : 要介護4+5の人数
ELIGIBLE_RULE_LABELS = {
    "all": "利用者全員",
    "dementia": "認知症自立度III以上の割合",
    "medical": "医療依存度が高い利用者の割合",
    "midHighCare": "要介護3以上の利用者",
    "heavyCare": "要介護4・5の利用者",
}


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
        requirement_process=[
            {"task": "利用者ごとのADL・栄養・口腔等の情報をLIFEへ提出",
             "owner": "介護職員/相談員(データ入力)", "frequency": "利用開始時および3ヶ月に1回",
             "deliverable": "LIFE提出用データ(CSV等)"},
            {"task": "LIFEからのフィードバックを踏まえたケア計画の見直し(PDCA)",
             "owner": "サービス提供責任者・生活相談員", "frequency": "フィードバック受領後1ヶ月以内",
             "deliverable": "見直し後のケア計画書"},
        ],
        variable_cost_items=[
            {"label": "LIFEデータ入力・PDCA会議の人件費(月2時間相当)", "basis": "per_month", "yen": 3600},
        ],
        requires_life_submission=True,
        system_initial_cost=0, training_annual_cost=50000, major=True,
        notes="人員要件なし。既存ソフトのLIFE連携機能があれば追加投資はほぼ不要。",
    ),
    AddonMaster(
        code="KOBETSU_KINOU_I",
        name="個別機能訓練加算(I)ロ",
        applicable_services=["通所介護"],
        unit_value=56, billing_basis="per_visit", monthly_frequency=22,
        requirement_staff={"rehab_staff_count": 1},
        requirement_process=[
            {"task": "個別機能訓練計画書の作成", "owner": "機能訓練指導員",
             "frequency": "利用開始時", "deliverable": "個別機能訓練計画書"},
            {"task": "目標達成度の評価・計画の見直し", "owner": "機能訓練指導員",
             "frequency": "3ヶ月ごと", "deliverable": "評価記録・改定後の計画書"},
            {"task": "生活機能向上を目的とした訓練の実施記録", "owner": "機能訓練指導員/介護職員",
             "frequency": "訓練実施の都度", "deliverable": "訓練実施記録"},
        ],
        variable_cost_items=[
            {"label": "訓練用具・消耗品費", "basis": "per_occurrence", "yen": 15},
        ],
        hiring_needed_role="機能訓練指導員(PT/OT/ST等)",
        hiring_annual_cost=4200000, training_annual_cost=0, major=True,
        staffing_lead_time="常勤・非常勤いずれも新規採用が必要。求人掲載から入職まで平均2〜3ヶ月を想定。",
        notes="専従1名(非常勤可)配置で算定可。常勤専従化で(II)への上位も検討可。",
    ),
    AddonMaster(
        code="KOUKUEIYOU_SCREEN",
        name="口腔・栄養スクリーニング加算(I)",
        applicable_services=["通所介護", "通所リハビリテーション"],
        unit_value=20, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "口腔・栄養状態のスクリーニングを実施し記録", "owner": "介護職員(生活相談員と連携)",
             "frequency": "6ヶ月に1回", "deliverable": "スクリーニング記録票"},
            {"task": "居宅介護支援事業所への情報提供", "owner": "生活相談員",
             "frequency": "スクリーニング実施後速やかに", "deliverable": "情報提供書"},
        ],
        variable_cost_items=[
            {"label": "スクリーニング実施・記録・情報提供の人件費(全利用者分・月平均30分相当)",
             "basis": "per_month", "yen": 900},
        ],
        major=True,
        notes="人員要件なし。既存職員での実施が可能なため難易度は低い。",
    ),
    AddonMaster(
        code="EIYOU_ASSESSMENT",
        name="栄養アセスメント加算",
        applicable_services=["通所介護", "通所リハビリテーション",
                              "特別養護老人ホーム", "介護老人保健施設"],
        unit_value=50, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"dietitian_count": 1},
        requirement_process=[
            {"task": "利用開始時の栄養アセスメントの実施", "owner": "管理栄養士",
             "frequency": "利用開始時", "deliverable": "栄養アセスメント記録"},
            {"task": "アセスメントの再実施", "owner": "管理栄養士",
             "frequency": "3ヶ月ごと", "deliverable": "再アセスメント記録"},
            {"task": "多職種連携での栄養ケア計画作成", "owner": "管理栄養士・看護師・介護職員",
             "frequency": "アセスメント実施の都度", "deliverable": "栄養ケア計画書"},
        ],
        variable_cost_items=[
            {"label": "栄養アセスメント用品・記録費", "basis": "per_occurrence", "yen": 20},
        ],
        hiring_needed_role="管理栄養士",
        hiring_annual_cost=4500000, major=True,
        staffing_lead_time="常勤採用が難しい場合、外部栄養士との業務委託(巡回型)も選択肢。委託契約なら1〜2ヶ月程度で開始可能。",
        notes="他事業所との連携(栄養士外部委託・巡回)で常勤雇用を回避できる場合あり。",
    ),
    AddonMaster(
        code="NINCHISHOU_SENMON_I",
        name="認知症専門ケア加算(I)",
        applicable_services=["通所介護", "訪問介護", "特別養護老人ホーム",
                              "介護老人保健施設", "グループホーム"],
        unit_value=3, billing_basis="per_day", monthly_frequency=22,
        requirement_staff={"trained_dementia_staff": 1},
        requirement_process=[
            {"task": "認知症日常生活自立度III以上の利用者割合の確認", "owner": "生活相談員/ケアマネジャー",
             "frequency": "月次", "deliverable": "利用者名簿・自立度一覧"},
            {"task": "認知症介護実践リーダー研修修了者の配置", "owner": "施設管理者",
             "frequency": "継続的要件", "deliverable": "研修修了証の保管"},
            {"task": "認知症ケアに関する会議の開催", "owner": "研修修了者が主導、関係職員が参加",
             "frequency": "月1回程度", "deliverable": "会議記録"},
        ],
        variable_cost_items=[
            {"label": "認知症ケア会議の人件費(月1回・3名×1時間)", "basis": "per_month", "yen": 5400},
        ],
        training_annual_cost=150000, eligible_rule="dementia", major=True,
        staffing_lead_time="研修修了者が未配置の場合、外部研修(認知症介護実践リーダー研修)の受講に数ヶ月〜半年を要する。",
        notes="対象者割合(認知症III以上が全体の1/2以上)を満たすかが最大の分岐点。",
    ),
    AddonMaster(
        code="SEISAN_TEISEI_KYOKA",
        name="サービス提供体制強化加算(I)",
        applicable_services=["通所介護", "訪問介護", "訪問看護",
                              "特別養護老人ホーム", "介護老人保健施設"],
        unit_value=22, billing_basis="per_visit", monthly_frequency=22,
        requirement_staff={},
        requirement_process=[
            {"task": "介護福祉士等の配置割合の算出・維持", "owner": "施設管理者",
             "frequency": "月次確認", "deliverable": "職員配置状況の記録"},
            {"task": "職員研修計画の策定・実施", "owner": "施設管理者/研修担当者",
             "frequency": "年間計画の策定+実施の都度", "deliverable": "研修計画書・実施記録"},
            {"task": "会議の定期開催", "owner": "施設管理者",
             "frequency": "月1回程度", "deliverable": "会議記録"},
        ],
        variable_cost_items=[
            {"label": "研修計画運営・会議の人件費(月2時間相当)", "basis": "per_month", "yen": 3600},
        ],
        major=True,
        notes="有資格者比率が既に高い事業所は追加投資ゼロで即算定可能な典型例。",
    ),
    AddonMaster(
        code="SEIKATSU_KINOU_RENKEI",
        name="生活機能向上連携加算(I)",
        applicable_services=["通所介護", "訪問介護"],
        unit_value=100, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "外部リハ専門職(訪問リハ・医療機関等)との連携先の確保", "owner": "施設管理者/生活相談員",
             "frequency": "契約時に一度、以降継続", "deliverable": "連携に関する契約書・同意書"},
            {"task": "外部専門職によるアセスメントへの同行・情報共有", "owner": "生活相談員/機能訓練指導員",
             "frequency": "3ヶ月に1回程度", "deliverable": "アセスメント結果共有記録"},
            {"task": "個別サービス計画への反映", "owner": "サービス提供責任者",
             "frequency": "アセスメント実施後", "deliverable": "改定後の個別サービス計画書"},
        ],
        variable_cost_items=[
            {"label": "外部リハ専門職との連携調整・アセスメント同行の人件費", "basis": "per_occurrence", "yen": 450},
        ],
        major=True,
        notes="自前でPT/OT/ST雇用不要。外部連携のみで算定可能な低コスト加算。",
    ),
    AddonMaster(
        code="NYUYOKU_KAIJO_II",
        name="入浴介助加算(II)",
        applicable_services=["通所介護"],
        unit_value=55, billing_basis="per_visit", monthly_frequency=18,
        requirement_staff={"rehab_staff_count": 0.1},
        requirement_process=[
            {"task": "利用者の居宅を訪問し浴室環境等をアセスメント",
             "owner": "機能訓練指導員/介護職員(医師等の助言を得て)",
             "frequency": "利用開始時および3ヶ月に1回程度", "deliverable": "居宅訪問アセスメント記録"},
            {"task": "個浴等、居宅の状況に近い環境での入浴介助計画の作成",
             "owner": "介護職員/機能訓練指導員", "frequency": "アセスメント実施後",
             "deliverable": "個別入浴介助計画書"},
            {"task": "計画に基づく入浴介助の実施・記録", "owner": "介護職員",
             "frequency": "入浴介助の都度", "deliverable": "入浴介助実施記録"},
        ],
        variable_cost_items=[
            {"label": "個浴対応による追加介助人件費(1回あたり約10分・時給1,800円換算)",
             "basis": "per_occurrence", "yen": 300},
            {"label": "水道・ガス代(個浴による使用量増加分)", "basis": "per_occurrence", "yen": 60},
            {"label": "洗浄剤・タオル等消耗品費", "basis": "per_occurrence", "yen": 25},
            {"label": "居宅訪問アセスメントの人件費(対象者を3ヶ月サイクルで巡回・月平均15時間相当)",
             "basis": "per_month", "yen": 30000},
        ],
        staffing_lead_time="既存職員のシフト再配置・兼務での対応を想定。0.1名相当の不足であれば運用変更は2〜4週間程度で開始可能。",
        major=True,
        notes="訪問アセスメント・個浴対応には人件費・水道代・消耗品費が継続的に発生する。追加雇用は小規模で済む場合が多いが「無償」ではない。",
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
        requirement_process=[
            {"task": "訪問介護員等の研修計画の策定・実施", "owner": "サービス提供責任者",
             "frequency": "年間計画の策定+実施の都度", "deliverable": "研修計画書・実施記録"},
            {"task": "会議の定期開催", "owner": "サービス提供責任者",
             "frequency": "月1回以上", "deliverable": "会議記録"},
            {"task": "重度要介護者等対応要件の確認", "owner": "サービス提供責任者",
             "frequency": "月次確認", "deliverable": "対象利用者一覧"},
            {"task": "サービス提供責任者の資格・配置要件の確認", "owner": "施設管理者",
             "frequency": "継続的要件", "deliverable": "資格証・配置記録"},
        ],
        variable_cost_items=[
            {"label": "研修・会議の人件費(月1回・5名×1時間)", "basis": "per_month", "yen": 9000},
        ],
        major=True,
        notes="加算率(総単位数の20%)型。人員要件・研修体制が整っていれば追加雇用なしで高収益。",
    ),
    AddonMaster(
        code="KANKYU_HOMON_KANGO",
        name="緊急時訪問看護加算",
        applicable_services=["訪問看護"],
        unit_value=574, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"nurse_count": 1},
        requirement_process=[
            {"task": "24時間連絡体制の確保(オンコール体制の構築)", "owner": "看護師/管理者",
             "frequency": "継続的要件", "deliverable": "連絡体制表・オンコール当番表"},
            {"task": "利用者への説明・同意取得", "owner": "看護師",
             "frequency": "利用開始時", "deliverable": "同意書"},
        ],
        variable_cost_items=[
            {"label": "オンコール待機手当(既存看護師への手当)", "basis": "per_month", "yen": 15000},
        ],
        hiring_needed_role=None, hiring_annual_cost=0, major=True,
        staffing_lead_time="既存看護師でオンコール当番を組める場合は増員不要。持ち回りが困難な体制規模であれば増員を検討。",
        notes="既存看護師でオンコール体制を組める場合、新規雇用は不要だが待機手当は発生する。",
    ),
    AddonMaster(
        code="NICHIJO_KEIZOKU",
        name="日常生活継続支援加算",
        applicable_services=["特別養護老人ホーム"],
        unit_value=36, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={"care_worker_ftv": 0},
        requirement_process=[
            {"task": "要介護4・5の入所者割合(7割以上)の確認", "owner": "施設管理者/ケアマネジャー",
             "frequency": "月次確認", "deliverable": "入所者要介護度一覧"},
            {"task": "介護福祉士の配置割合要件の確認・維持", "owner": "施設管理者",
             "frequency": "月次確認", "deliverable": "職員配置状況の記録"},
        ],
        variable_cost_items=[
            {"label": "重度者ケアに伴う追加人件費(1日あたり)", "basis": "per_occurrence", "yen": 120},
        ],
        eligible_rule="heavyCare", major=True,
        notes="重度者割合と介護福祉士比率の2条件。人員要件充足がボトルネックになりやすい。",
    ),
    AddonMaster(
        code="HAISETSU_SHIEN",
        name="排せつ支援加算(I)",
        applicable_services=["特別養護老人ホーム", "介護老人保健施設"],
        unit_value=10, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "医師・看護師・介護支援専門員等による排せつ状態の評価", "owner": "多職種チーム",
             "frequency": "3ヶ月に1回", "deliverable": "排せつ評価記録"},
            {"task": "支援計画の作成と見直し", "owner": "介護支援専門員",
             "frequency": "評価実施後、3ヶ月ごと", "deliverable": "排せつ支援計画書"},
            {"task": "LIFEへのデータ提出", "owner": "介護支援専門員/データ入力担当",
             "frequency": "3ヶ月に1回", "deliverable": "LIFE提出用データ"},
        ],
        variable_cost_items=[
            {"label": "多職種評価・計画作成の人件費(3ヶ月サイクル・月平均相当)", "basis": "per_month", "yen": 3300},
        ],
        requires_life_submission=True, major=True,
        notes="多職種評価さえ運用化できれば追加投資は小さいが、評価・会議の人件費は継続的に発生する。",
    ),

    # ---- 以下、v3で追加(通所介護等7サービス類型の主要加算を拡充) ----

    AddonMaster(
        code="KAIGO_SHOGU_KAIZEN",
        name="介護職員等処遇改善加算",
        applicable_services=["通所介護", "訪問介護", "訪問看護", "特別養護老人ホーム",
                              "介護老人保健施設", "通所リハビリテーション", "グループホーム"],
        unit_value=300, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "賃金改善計画の策定・実施", "owner": "施設管理者", "frequency": "年度ごとに策定、毎月実施",
             "deliverable": "処遇改善計画書"},
            {"task": "実績報告書の提出", "owner": "施設管理者", "frequency": "年1回", "deliverable": "処遇改善実績報告書"},
        ],
        variable_cost_items=[
            {"label": "計画書・実績報告書作成の事務人件費(月2時間相当)", "basis": "per_month", "yen": 3600},
        ],
        major=True,
        notes="実際は総単位数に対する加算率(区分I〜IVで異なる)で算定される。ここでは月額換算した簡易モデル。",
    ),
    AddonMaster(
        code="KOBETSU_KINOU_II",
        name="個別機能訓練加算(II)",
        applicable_services=["通所介護"],
        unit_value=20, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requires_life_submission=True,
        requirement_process=[
            {"task": "LIFEへの訓練データ提出とフィードバックの活用", "owner": "機能訓練指導員",
             "frequency": "3ヶ月に1回", "deliverable": "LIFE提出用データ"},
        ],
        variable_cost_items=[],
        notes="個別機能訓練加算(I)の上乗せ加算。(I)の算定とLIFE提出が前提。",
    ),
    AddonMaster(
        code="NYUYOKU_KAIJO_I",
        name="入浴介助加算(I)",
        applicable_services=["通所介護"],
        unit_value=40, billing_basis="per_visit", monthly_frequency=18,
        requirement_staff={},
        requirement_process=[
            {"task": "入浴介助を行う際の環境整備・見守り等の基本要件確認", "owner": "介護職員",
             "frequency": "継続的要件", "deliverable": "入浴介助に関する記録"},
        ],
        variable_cost_items=[
            {"label": "入浴介助人件費(基本)", "basis": "per_occurrence", "yen": 100},
        ],
        notes="入浴介助加算(II)より基本的な要件。(II)への上位変更(居宅訪問アセスメント等)も検討可。",
    ),
    AddonMaster(
        code="CHUJUDO_CARE_TAISEI",
        name="中重度者ケア体制加算",
        applicable_services=["通所介護", "通所リハビリテーション"],
        eligible_rule="midHighCare",
        unit_value=45, billing_basis="per_visit", monthly_frequency=20,
        requirement_staff={"care_worker_ftv": 2},
        requirement_process=[
            {"task": "看護職員・介護職員の加配状況の確認", "owner": "施設管理者", "frequency": "月次確認",
             "deliverable": "職員配置記録"},
        ],
        variable_cost_items=[
            {"label": "加配職員の人件費(既存シフトでの対応分)", "basis": "per_month", "yen": 15000},
        ],
        hiring_needed_role="介護職員(加配)", hiring_annual_cost=3800000,
        staffing_lead_time="加配職員の確保に非常勤採用で1〜2ヶ月程度を想定。",
        notes="要介護3以上の利用者割合が一定以上であることに加え、看護・介護職員の加配が要件。",
    ),
    AddonMaster(
        code="WAKANENSEI_NINCHISHOU",
        name="若年性認知症利用者受入加算",
        applicable_services=["通所介護", "通所リハビリテーション", "グループホーム"],
        eligible_rule="dementia",
        unit_value=60, billing_basis="per_visit", monthly_frequency=20,
        requirement_staff={},
        requirement_process=[
            {"task": "若年性認知症の利用者ごとの担当者配置", "owner": "生活相談員", "frequency": "利用開始時",
             "deliverable": "担当者配置記録"},
        ],
        variable_cost_items=[],
        notes="本来は65歳未満の若年性認知症の利用者が対象。ここでは認知症自立度の割合を簡易的な代理指標として使用しており、実際の対象者数とは異なる点に注意。",
    ),
    AddonMaster(
        code="EIYOU_KAIZEN",
        name="栄養改善加算",
        applicable_services=["通所介護", "通所リハビリテーション"],
        unit_value=200, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"dietitian_count": 1},
        requirement_process=[
            {"task": "栄養改善サービス計画の作成・実施", "owner": "管理栄養士", "frequency": "月2回程度",
             "deliverable": "栄養改善サービス計画書"},
        ],
        variable_cost_items=[
            {"label": "栄養改善プログラム実施費", "basis": "per_occurrence", "yen": 50},
        ],
        hiring_needed_role="管理栄養士", hiring_annual_cost=4500000,
        notes="栄養アセスメント加算とは別建て。低栄養リスクのある利用者向けの個別プログラム。",
    ),
    AddonMaster(
        code="KOKU_KINOU_KOJO_I",
        name="口腔機能向上加算(I)",
        applicable_services=["通所介護", "通所リハビリテーション"],
        unit_value=150, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "口腔機能改善管理指導計画の作成", "owner": "歯科衛生士/言語聴覚士等",
             "frequency": "利用開始時・3ヶ月毎", "deliverable": "口腔機能改善管理指導計画書"},
        ],
        variable_cost_items=[
            {"label": "口腔機能向上プログラム実施費", "basis": "per_occurrence", "yen": 40},
        ],
        notes="低栄養・口腔機能低下リスクのある利用者向け。歯科衛生士等の配置または連携が必要。",
    ),
    AddonMaster(
        code="IRYORENKEI_KYOKA",
        name="医療連携強化加算",
        applicable_services=["通所介護"],
        eligible_rule="medical",
        unit_value=56, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"nurse_count": 1},
        requirement_process=[
            {"task": "医療的ケアが必要な利用者の状態把握・主治医等との連携", "owner": "看護師",
             "frequency": "利用の都度", "deliverable": "医療連携記録"},
        ],
        variable_cost_items=[
            {"label": "主治医等との連携調整費", "basis": "per_month", "yen": 5000},
        ],
        notes="医療的ケアが必要な利用者への対応体制を評価する加算。",
    ),
    AddonMaster(
        code="SEIKATSU_SOUDAN_HAICHI",
        name="生活相談員配置等加算",
        applicable_services=["通所介護"],
        unit_value=13, billing_basis="per_visit", monthly_frequency=22,
        requirement_staff={},
        requirement_process=[
            {"task": "サービス提供時間帯を通じた生活相談員の配置", "owner": "生活相談員",
             "frequency": "営業日ごと", "deliverable": "職員配置記録"},
        ],
        variable_cost_items=[
            {"label": "生活相談員配置に伴う人件費(既存兼務分)", "basis": "per_month", "yen": 20000},
        ],
        notes="通常の配置に加えて生活相談員を配置する場合に算定可能な、地域密着型等向けの加算。",
    ),
    AddonMaster(
        code="SHOKAI_KASAN",
        name="初回加算",
        applicable_services=["訪問介護"],
        unit_value=200, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "サービス提供責任者による初回訪問", "owner": "サービス提供責任者",
             "frequency": "利用開始月のみ", "deliverable": "初回訪問記録"},
        ],
        variable_cost_items=[],
        notes="新規利用者の利用開始月のみ算定される一時的な加算。継続算定を前提とした本モデルでは収益を過大評価しやすい点に注意。",
    ),
    AddonMaster(
        code="KINKYUJI_HOMON_KAIGO",
        name="緊急時訪問介護加算",
        applicable_services=["訪問介護"],
        unit_value=100, billing_basis="per_visit", monthly_frequency=2,
        requirement_staff={},
        requirement_process=[
            {"task": "計画外の緊急訪問に対応できる体制の構築", "owner": "サービス提供責任者",
             "frequency": "継続的要件", "deliverable": "緊急時対応記録"},
        ],
        variable_cost_items=[
            {"label": "緊急対応の待機・出動人件費", "basis": "per_occurrence", "yen": 500},
        ],
        notes="居宅介護支援事業所からの依頼により計画外の緊急訪問を行った場合に算定。",
    ),
    AddonMaster(
        code="NININ_HOMON",
        name="2人の訪問介護員等による訪問加算",
        applicable_services=["訪問介護"],
        unit_value=100, billing_basis="per_visit", monthly_frequency=5,
        requirement_staff={},
        requirement_process=[
            {"task": "複数名対応が必要な利用者の把握", "owner": "サービス提供責任者",
             "frequency": "ケアプラン作成時", "deliverable": "複数名対応の記録"},
        ],
        variable_cost_items=[
            {"label": "2人目の訪問介護員の人件費", "basis": "per_occurrence", "yen": 1800},
        ],
        notes="体重が重い利用者の入浴介助等、2名対応が必要と認められるケースに限り算定可能。",
    ),
    AddonMaster(
        code="TOKUBETSU_CHIIKI_HOMON",
        name="特別地域訪問介護加算",
        applicable_services=["訪問介護", "訪問看護"],
        unit_value=30, billing_basis="per_visit", monthly_frequency=25,
        requirement_staff={},
        requirement_process=[
            {"task": "事業所が中山間地域等の指定地域に所在することの確認", "owner": "施設管理者",
             "frequency": "指定時に一度", "deliverable": "地域指定の確認書類"},
        ],
        variable_cost_items=[],
        notes="事業所が厚生労働大臣が定める中山間地域等に所在する場合のみ算定可能。実際は総単位数への加算率(+15%程度)。",
    ),
    AddonMaster(
        code="TOKUBETSU_KANRI_I",
        name="特別管理加算(I)",
        applicable_services=["訪問看護"],
        eligible_rule="medical",
        unit_value=500, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "重症度の高い利用者の状態観察・特別な管理の実施", "owner": "看護師",
             "frequency": "訪問の都度", "deliverable": "特別管理に関する記録"},
        ],
        variable_cost_items=[
            {"label": "特別な処置・管理に伴う追加人件費", "basis": "per_month", "yen": 8000},
        ],
        major=True,
        notes="人工呼吸器管理等の重症度の高い利用者が対象。(II)はより軽度な要件で単位数も低い。",
    ),
    AddonMaster(
        code="TERMINAL_CARE_HOMONKANGO",
        name="ターミナルケア加算",
        applicable_services=["訪問看護"],
        eligible_rule="medical",
        unit_value=2500, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "終末期における24時間対応体制の確保とケア記録", "owner": "看護師",
             "frequency": "継続的要件", "deliverable": "ターミナルケア記録"},
        ],
        variable_cost_items=[
            {"label": "24時間対応体制の維持費(オンコール等)", "basis": "per_month", "yen": 20000},
        ],
        notes="実際は死亡月に一括算定される一時的な加算。継続算定を前提とした本モデルでは過大評価となる点に注意。",
    ),
    AddonMaster(
        code="KANGO_TAISEI_KYOKA_HOMON",
        name="看護体制強化加算",
        applicable_services=["訪問看護"],
        unit_value=550, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"nurse_count": 2},
        requirement_process=[
            {"task": "重症度の高い利用者の受入比率の維持", "owner": "管理者", "frequency": "月次確認",
             "deliverable": "利用者状況記録"},
        ],
        variable_cost_items=[
            {"label": "体制強化に伴う運用コスト", "basis": "per_month", "yen": 10000},
        ],
        notes="緊急時訪問看護加算・特別管理加算の算定割合等の要件がある。",
    ),
    AddonMaster(
        code="FUKUSU_MEI_HOMONKANGO",
        name="複数名訪問看護加算",
        applicable_services=["訪問看護"],
        unit_value=150, billing_basis="per_visit", monthly_frequency=4,
        requirement_staff={},
        requirement_process=[
            {"task": "複数名での訪問が必要な利用者の把握", "owner": "看護師", "frequency": "訪問計画作成時",
             "deliverable": "複数名訪問の記録"},
        ],
        variable_cost_items=[
            {"label": "2人目職員の人件費", "basis": "per_occurrence", "yen": 2500},
        ],
        notes="利用者の状態から複数名での訪問看護が必要と判断される場合に算定。",
    ),
    AddonMaster(
        code="KANGO_TAISEI_I_TOKUYO",
        name="看護体制加算(I)",
        applicable_services=["特別養護老人ホーム"],
        unit_value=6, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={"nurse_count": 1},
        requirement_process=[
            {"task": "看護職員の配置基準の充足確認", "owner": "施設管理者", "frequency": "月次確認",
             "deliverable": "職員配置記録"},
        ],
        variable_cost_items=[],
        notes="看護職員を常勤換算1名以上、基準を上回って配置している場合に算定可能。",
    ),
    AddonMaster(
        code="YAKIN_SHOKUIN_HAICHI",
        name="夜勤職員配置加算",
        applicable_services=["特別養護老人ホーム", "介護老人保健施設"],
        unit_value=22, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={},
        requirement_process=[
            {"task": "基準を上回る夜勤職員の配置", "owner": "施設管理者", "frequency": "継続的要件",
             "deliverable": "夜勤シフト表"},
        ],
        variable_cost_items=[
            {"label": "夜勤加配に伴う人件費(既存職員のシフト増)", "basis": "per_month", "yen": 80000},
        ],
        staffing_lead_time="既存職員のシフト調整で対応できない場合は非常勤の新規採用に1〜2ヶ月程度を想定。",
        notes="最低基準を上回る夜勤職員配置が必要。新規雇用が必要になるケースも多い点に留意。",
    ),
    AddonMaster(
        code="KEIKOU_IKO",
        name="経口移行加算",
        applicable_services=["特別養護老人ホーム", "介護老人保健施設"],
        eligible_rule="medical",
        unit_value=28, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={},
        requirement_process=[
            {"task": "経管栄養から経口摂取への移行計画の作成・実施", "owner": "医師・管理栄養士・看護師",
             "frequency": "個別の状態に応じて", "deliverable": "経口移行計画書"},
        ],
        variable_cost_items=[
            {"label": "多職種による移行支援の人件費", "basis": "per_occurrence", "yen": 80},
        ],
        notes="経管栄養を実施している利用者が対象。算定期間は原則180日以内。",
    ),
    AddonMaster(
        code="MITORI_KAIGO_TOKUYO",
        name="看取り介護加算",
        applicable_services=["特別養護老人ホーム"],
        eligible_rule="medical",
        unit_value=150, billing_basis="per_day", monthly_frequency=10,
        requirement_staff={},
        requirement_process=[
            {"task": "看取りに関する指針の整備と本人・家族への説明", "owner": "医師・看護師・介護職員",
             "frequency": "入所時および状態変化時", "deliverable": "看取り介護に関する指針・記録"},
        ],
        variable_cost_items=[
            {"label": "看取り期の集中的な人件費", "basis": "per_occurrence", "yen": 300},
        ],
        notes="実際は死亡日からの遡り日数に応じた段階的な単位設定。ここでは簡易的な代表値を使用。",
    ),
    AddonMaster(
        code="ANZEN_TAISAKU_TAISEI",
        name="安全対策体制加算",
        applicable_services=["特別養護老人ホーム", "介護老人保健施設"],
        unit_value=20, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "安全対策担当者の配置と事故防止研修の実施", "owner": "施設管理者",
             "frequency": "研修は年1回以上", "deliverable": "安全対策計画・研修記録"},
        ],
        variable_cost_items=[
            {"label": "研修費用", "basis": "per_month", "yen": 2000},
        ],
        notes="専任の安全対策担当者の配置が要件。",
    ),
    AddonMaster(
        code="JIRITSU_SHIEN_SOKUSHIN",
        name="自立支援促進加算",
        applicable_services=["特別養護老人ホーム", "介護老人保健施設"],
        unit_value=280, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requires_life_submission=True,
        requirement_process=[
            {"task": "医師による自立支援に係る医学的評価の実施", "owner": "医師・介護支援専門員",
             "frequency": "6ヶ月に1回", "deliverable": "自立支援に関する評価書"},
        ],
        variable_cost_items=[
            {"label": "医師による評価費用", "basis": "per_occurrence", "yen": 150},
        ],
        notes="医師の指示に基づくADL等の改善に向けた支援計画が要件。LIFEへの提出も必要。",
    ),
    AddonMaster(
        code="ZAITAKU_FUKKI_KINOU",
        name="在宅復帰・在宅療養支援機能加算",
        applicable_services=["介護老人保健施設"],
        unit_value=34, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={},
        requirement_process=[
            {"task": "在宅復帰率・ベッド回転率等の実績要件の維持", "owner": "施設管理者・支援相談員",
             "frequency": "月次確認", "deliverable": "在宅復帰率等の実績記録"},
        ],
        variable_cost_items=[
            {"label": "在宅復帰支援に係る相談員の人件費", "basis": "per_month", "yen": 30000},
        ],
        notes="在宅復帰率・ベッド回転率・要介護度等の複数指標が要件。",
    ),
    AddonMaster(
        code="NINCHISHOU_JOHO_TEIKYO",
        name="認知症情報提供加算",
        applicable_services=["介護老人保健施設"],
        eligible_rule="dementia",
        unit_value=350, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "退所時に認知症に関する情報を提供", "owner": "支援相談員", "frequency": "退所時",
             "deliverable": "情報提供書"},
        ],
        variable_cost_items=[],
        notes="退所時に一度限り算定される加算。継続算定を前提とした本モデルでは過大評価となる点に注意。",
    ),
    AddonMaster(
        code="REHA_MANAGEMENT_A",
        name="リハビリテーションマネジメント加算(A)",
        applicable_services=["通所リハビリテーション"],
        unit_value=180, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"rehab_staff_count": 1},
        requires_life_submission=True,
        requirement_process=[
            {"task": "リハビリテーション計画の医師説明・多職種会議の実施", "owner": "医師・PT/OT/ST",
             "frequency": "3ヶ月に1回", "deliverable": "リハビリテーション計画書"},
        ],
        variable_cost_items=[
            {"label": "多職種会議の人件費", "basis": "per_month", "yen": 9000},
        ],
        notes="LIFEへのデータ提出とフィードバック活用が要件。(B)はさらに上位の医師関与要件。",
    ),
    AddonMaster(
        code="SEIKATSU_KOI_KOJO_REHA",
        name="生活行為向上リハビリテーション実施加算",
        applicable_services=["通所リハビリテーション"],
        unit_value=1250, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={"rehab_staff_count": 1},
        requirement_process=[
            {"task": "生活行為の内容の充実に着目したプログラムの提供", "owner": "PT/OT/ST",
             "frequency": "3ヶ月間集中的に実施", "deliverable": "生活行為向上プログラム記録"},
        ],
        variable_cost_items=[
            {"label": "集中的なリハプログラム実施費", "basis": "per_month", "yen": 15000},
        ],
        notes="算定期間は原則3ヶ月以内に限定される時限的な加算。継続算定を前提とした本モデルでは過大評価となる点に注意。",
    ),
    AddonMaster(
        code="IKO_SHIEN",
        name="移行支援加算",
        applicable_services=["通所リハビリテーション"],
        unit_value=17, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "通所介護等の他サービスへの移行実績の記録", "owner": "支援相談員",
             "frequency": "評価対象期間ごと", "deliverable": "移行実績記録"},
        ],
        variable_cost_items=[],
        notes="評価対象期間ごとの移行率に応じて算定可否が決まる実績評価型の加算。",
    ),
    AddonMaster(
        code="IRYORENKEI_TAISEI_GH",
        name="医療連携体制加算",
        applicable_services=["グループホーム"],
        eligible_rule="medical",
        unit_value=39, billing_basis="per_day", monthly_frequency=30,
        requirement_staff={"nurse_count": 1},
        requirement_process=[
            {"task": "看護師による定期的な健康管理と医療機関との連携体制の構築", "owner": "看護師",
             "frequency": "継続的要件", "deliverable": "医療連携体制の記録"},
        ],
        variable_cost_items=[
            {"label": "看護師の医療連携対応に係る人件費", "basis": "per_month", "yen": 25000},
        ],
        notes="看護師の配置または医療機関との連携体制が要件。",
    ),
    AddonMaster(
        code="MITORI_KAIGO_GH",
        name="看取り介護加算",
        applicable_services=["グループホーム"],
        eligible_rule="medical",
        unit_value=150, billing_basis="per_day", monthly_frequency=10,
        requirement_staff={},
        requirement_process=[
            {"task": "看取りに関する指針の整備と本人・家族への説明", "owner": "医師・看護師・介護職員",
             "frequency": "入居時および状態変化時", "deliverable": "看取りに関する指針・記録"},
        ],
        variable_cost_items=[
            {"label": "看取り期の集中的な人件費", "basis": "per_occurrence", "yen": 300},
        ],
        notes="特養と同様の考え方。実際は死亡日からの遡り日数に応じた段階設定。",
    ),
    AddonMaster(
        code="NINCHISHOU_KOUDOU_SHINRI",
        name="認知症行動・心理症状緊急対応加算",
        applicable_services=["グループホーム", "特別養護老人ホーム", "介護老人保健施設"],
        eligible_rule="dementia",
        unit_value=200, billing_basis="per_month", monthly_frequency=1,
        requirement_staff={},
        requirement_process=[
            {"task": "BPSDの急性増悪時における医師の判断に基づく緊急対応", "owner": "医師・介護職員",
             "frequency": "急性増悪時", "deliverable": "緊急対応の記録"},
        ],
        variable_cost_items=[
            {"label": "緊急対応に伴う集中的な人件費", "basis": "per_occurrence", "yen": 500},
        ],
        notes="医師が判断した急性増悪から7日間を限度とする時限的な加算。継続算定を前提とした本モデルでは過大評価となる点に注意。",
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


def compute_eligible_users(facility: FacilityInput, addon: AddonMaster) -> float:
    """加算の対象となる利用者数を、addon.eligible_rule に従って概算する。
    収益試算とコスト試算の両方から参照することで、対象人数の扱いを一致させる
    (でないと収益とコストのスケールがずれて不整合な結果になる)。
    """
    u = facility.users
    total_users = u.total_users or 1
    rule = addon.eligible_rule

    if rule == "dementia":
        return total_users * u.dementia_ratio
    if rule == "medical":
        return total_users * u.high_medical_need_ratio
    if rule == "midHighCare":
        return u.care3 + u.care4 + u.care5
    if rule == "heavyCare":
        return u.care4 + u.care5
    return total_users


BILLING_BASIS_LABEL = {
    "per_visit": "利用1回ごとに算定",
    "per_month": "月1回・月額として算定",
    "per_day": "利用1日ごとに算定",
}


def describe_eligible_users(facility: FacilityInput, addon: AddonMaster) -> dict:
    """対象利用者数を、その根拠の説明文つきで返す。「なぜこの人数なのか」を
    ①の収益内訳に表示するための補助情報(count は compute_eligible_users と必ず一致させる)。
    """
    u = facility.users
    total = u.total_users or 1
    rule = addon.eligible_rule

    if rule == "dementia":
        pct = u.dementia_ratio * 100
        count = total * u.dementia_ratio
        desc = f"利用者全員({u.total_users}名) × 認知症自立度III以上の割合({pct:.0f}%) = {count:.2f}名が対象"
    elif rule == "medical":
        pct = u.high_medical_need_ratio * 100
        count = total * u.high_medical_need_ratio
        desc = f"利用者全員({u.total_users}名) × 医療依存度が高い利用者の割合({pct:.0f}%) = {count:.2f}名が対象"
    elif rule == "midHighCare":
        count = u.care3 + u.care4 + u.care5
        desc = f"要介護3({u.care3}名) + 要介護4({u.care4}名) + 要介護5({u.care5}名) = {count:.0f}名が対象"
    elif rule == "heavyCare":
        count = u.care4 + u.care5
        desc = f"要介護4({u.care4}名) + 要介護5({u.care5}名) = {count:.0f}名が対象"
    else:
        count = total
        desc = f"利用者全員({u.total_users}名)が対象"

    return {"count": count, "description": desc}


def estimate_annual_revenue(facility: FacilityInput, addon: AddonMaster) -> float:
    """STEP2: 加算による想定年間請求増加額を算出する。"""
    eligible = compute_eligible_users(facility, addon)
    monthly_units = addon.unit_value * addon.monthly_frequency * eligible
    monthly_yen = monthly_units * facility.unit_price
    return round(monthly_yen * 12, 0)


def build_revenue_breakdown(facility: FacilityInput, addon: AddonMaster) -> dict:
    """①の「年間増収見込み」がどう計算されたかを、要素分解して返す。
    単位数×算定頻度×対象利用者数×地域区分単価×12ヶ月、という計算式の
    各項目の値と、対象利用者数の根拠を表示できるようにする。
    """
    eligible_info = describe_eligible_users(facility, addon)
    eligible = eligible_info["count"]
    monthly_units = addon.unit_value * addon.monthly_frequency * eligible
    monthly_yen = monthly_units * facility.unit_price
    annual_yen = round(monthly_yen * 12, 0)

    formula = (f"{addon.unit_value}単位 × {addon.monthly_frequency}回/月 × "
               f"{eligible:.2f}名 × {facility.unit_price}円/単位 × 12ヶ月 = {annual_yen:,.0f}円")

    return {
        "unit_value": addon.unit_value,
        "billing_basis_label": BILLING_BASIS_LABEL.get(addon.billing_basis, addon.billing_basis),
        "monthly_frequency": addon.monthly_frequency,
        "eligible_count": eligible,
        "eligible_description": eligible_info["description"],
        "unit_price": facility.unit_price,
        "region_class": facility.region_class,
        "formula": formula,
        "annual_yen": annual_yen,
    }


def estimate_annual_cost(facility: FacilityInput, addon: AddonMaster, gap: dict) -> dict:
    """STEP3: 初期コストとランニングコストを、費目ごとに内訳付きで見積もる。

    v2では「新規雇用が必要な場合の人件費」に加えて、既存職員が対応する場合でも
    発生する稼働時間の人件費・水道代・消耗品費(variable_cost_items)を計上する。
    既存職員が対応する加算のランニングコストが0円になってしまうのを避けるための変更。
    """
    breakdown = []
    initial_cost = addon.system_initial_cost
    eligible = compute_eligible_users(facility, addon)

    if gap["staffing_gap"] > 0 and addon.hiring_needed_role:
        hire_cost = addon.hiring_annual_cost * min(gap["staffing_gap"], 1.0)
        breakdown.append({"label": f"新規雇用人件費({addon.hiring_needed_role})", "annual_yen": hire_cost})

    if addon.training_annual_cost:
        breakdown.append({"label": "研修費用", "annual_yen": addon.training_annual_cost})

    if gap["system_gap"] > 0:
        sys_cost = gap["system_gap"] * 100000
        breakdown.append({"label": "システム非対応分の運用工数(LIFE対応)", "annual_yen": sys_cost})

    for item in addon.variable_cost_items:
        if item["basis"] == "per_month":
            annual_yen = item["yen"] * 12
        else:  # per_occurrence
            annual_yen = item["yen"] * addon.monthly_frequency * eligible * 12
        breakdown.append({"label": item["label"], "annual_yen": round(annual_yen, 0)})

    running_cost_annual = sum(b["annual_yen"] for b in breakdown)
    return {"initial_cost": initial_cost, "running_cost_annual": running_cost_annual, "breakdown": breakdown}


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
    """STEP6: 要件クリアへのロードマップを、フェーズ構造で生成する。

    v2では単純な一行ステップの列挙から、
    「Phase1 人員体制 → Phase2 運用ルールの構築(担当・頻度・記録物を明示) →
      Phase3 システム・記録対応 → Phase4 届出・算定開始 → Phase5 継続運用」
    という進め方が分かる構造に変更した。
    """
    phases = []

    if gap["staffing_gap"] > 0:
        role = addon.hiring_needed_role or "必要職種(既存職員の再配置・兼務を含む)"
        phases.append({
            "phase": "Phase 1: 人員体制の整備",
            "lead_time": addon.staffing_lead_time or "体制整備に要する期間は個別に確認が必要。",
            "items": [
                f"{role}を常勤換算 {gap['staffing_gap']:.2f} 名相当、新規雇用・外部委託・既存職員の再配置のいずれかで確保する。",
            ],
        })

    if addon.requirement_process:
        phases.append({
            "phase": "Phase 2: 運用ルールの構築",
            "items": list(addon.requirement_process),  # 各要素: task/owner/frequency/deliverable
        })

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
        phases.append({"phase": "Phase 3: システム・記録対応", "items": [sys_note]})

    phases.append({
        "phase": "Phase 4: 届出・算定開始",
        "items": [
            "体制等状況一覧表(様式は管轄自治体のホームページで公開)に必要事項を記入し、加算根拠となる計画書等の写しを添えて提出する。",
            "提出先は事業所所在地を管轄する都道府県または市町村の介護保険担当課。",
            "算定開始日は提出月の翌月1日からとする運用が一般的だが、詳細は自治体の運用に従うこと。",
        ],
    })

    phases.append({
        "phase": "Phase 5: 継続運用・見直し(算定後も継続)",
        "items": [
            "Phase 2で整備した記録を継続的に作成・保管する(指定基準上、原則5年間の保存義務)。",
            "要件を満たさなくなった場合は速やかに加算の算定を中止し、必要に応じて変更届を提出する。",
            "報酬改定(3年ごと)・処遇改善加算等の毎年の運用見直しのタイミングで、本マスタの単位数・要件を再確認する。",
        ],
    })

    return phases


@dataclass
class AddonResult:
    addon: AddonMaster
    gap: dict
    annual_revenue: float
    revenue_breakdown: dict
    initial_cost: float
    running_cost_annual: float
    cost_breakdown: list
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

        revenue_breakdown = build_revenue_breakdown(facility, addon)
        revenue = revenue_breakdown["annual_yen"]
        cost = estimate_annual_cost(facility, addon, gap)
        amortized_initial = cost["initial_cost"] / 5  # 初期投資を5年償却で年換算
        net_profit = revenue - cost["running_cost_annual"] - amortized_initial
        difficulty = compute_difficulty_score(gap)
        roadmap = generate_roadmap(facility, addon, gap)

        results.append(AddonResult(
            addon=addon, gap=gap, annual_revenue=revenue, revenue_breakdown=revenue_breakdown,
            initial_cost=cost["initial_cost"],
            running_cost_annual=cost["running_cost_annual"],
            cost_breakdown=cost["breakdown"],
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
                "年間増収の算出根拠": {
                    "単位数": f"{r.revenue_breakdown['unit_value']}単位",
                    "算定基準": r.revenue_breakdown["billing_basis_label"],
                    "想定算定回数": f"{r.revenue_breakdown['monthly_frequency']}回/月",
                    "対象利用者数": r.revenue_breakdown["eligible_description"],
                    "地域区分単価": f"{r.revenue_breakdown['unit_price']}円/単位({r.revenue_breakdown['region_class']})",
                    "計算式": r.revenue_breakdown["formula"],
                },
                "年間追加コスト": f"{(r.running_cost_annual + r.initial_cost/5):,.0f}円",
                "年間純利益": f"{r.net_annual_profit:,.0f}円",
                "赤字警告": r.net_annual_profit < 0,
            } for r in cost_effectiveness_rank
        ],
        "② コスト見積もり(内訳付き)": [
            {
                "加算名": r.addon.name,
                "初期コスト": f"{r.initial_cost:,.0f}円",
                "ランニングコスト(年間)": f"{r.running_cost_annual:,.0f}円",
                "内訳": [f"{b['label']}: 年間{b['annual_yen']:,.0f}円" for b in r.cost_breakdown],
            } for r in results
        ],
        "③ 獲得ロードマップ": [
            {"加算名": r.addon.name, "フェーズ": r.roadmap} for r in cost_effectiveness_rank
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
