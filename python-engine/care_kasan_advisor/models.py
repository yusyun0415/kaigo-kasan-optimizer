"""
介護報酬加算 提案システム - データモデル定義

入力データ(施設プロファイル)と、加算マスタ(知識ベース)の型を定義する。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# A. 業務形態
# ---------------------------------------------------------------------------
class ServiceCategory(str, Enum):
    FACILITY = "施設型"      # 特養, 老健, 介護医療院 など
    DAYCARE = "通所型"       # デイサービス, 通所リハ など
    HOMEVISIT = "訪問型"     # 訪問介護, 訪問看護 など
    OTHER = "その他"         # 小規模多機能, グループホーム など


class BillingBasis(str, Enum):
    PER_USER_PER_DAY = "PER_USER_PER_DAY"       # 対象者数 × サービス提供日数
    PER_USER_PER_MONTH = "PER_USER_PER_MONTH"   # 対象者数 × 月1回
    FACILITY_PER_MONTH = "FACILITY_PER_MONTH"   # 事業所単位で月1回
    PER_VISIT = "PER_VISIT"                     # 訪問回数ベース
    PERCENTAGE_OF_BILLING = "PERCENTAGE_OF_BILLING"  # 総単位数に対する加算率


# ---------------------------------------------------------------------------
# B. 人員配置・専門職の情報
# ---------------------------------------------------------------------------
@dataclass
class StaffInfo:
    care_workers_ftk: float = 0.0            # 常勤換算 介護職員数
    nurses_ftk: float = 0.0                  # 常勤換算 看護職員数
    dietitian_count: int = 0                 # 管理栄養士人数(非常勤含む、外部連携は別途フラグ)
    dietitian_external_partnership: bool = False  # 外部の管理栄養士と連携している場合
    dietitian_hours_per_week: float = 0.0    # 管理栄養士の週間配置時間
    rehab_staff_count: int = 0               # PT/OT/ST 人数
    care_manager_count: int = 0              # ケアマネジャー人数
    care_worker_certified_ratio: float = 0.0  # 介護福祉士資格保有割合(0.0-1.0)


# ---------------------------------------------------------------------------
# C. 利用者(入所者)のステータス
# ---------------------------------------------------------------------------
@dataclass
class UserComposition:
    support_level_counts: dict            # {1: n, 2: n}  要支援1-2
    care_level_counts: dict               # {1: n, ..., 5: n}  要介護1-5
    dementia_high_ratio: float = 0.0      # 認知症高齢者の日常生活自立度 III以上の割合(0.0-1.0)
    medical_dependency_ratio: float = 0.0  # 医療依存度が高い利用者の割合(0.0-1.0)

    @property
    def total_users(self) -> int:
        return sum(self.support_level_counts.values()) + sum(self.care_level_counts.values())

    @property
    def care_only_users(self) -> int:
        return sum(self.care_level_counts.values())

    @property
    def mid_to_heavy_users(self) -> int:
        """要介護3-5 (中重度者)"""
        return sum(n for level, n in self.care_level_counts.items() if level >= 3)


# ---------------------------------------------------------------------------
# D. 現在の加算取得状況
# ---------------------------------------------------------------------------
@dataclass
class CurrentStatus:
    acquired: set = field(default_factory=set)          # 取得済み加算コード
    near_acquisition: set = field(default_factory=set)  # 要件をほぼ満たしている加算コード


# ---------------------------------------------------------------------------
# 入力データ全体(施設プロファイル)
# ---------------------------------------------------------------------------
@dataclass
class FacilityProfile:
    service_category: ServiceCategory
    service_type: str                    # 具体的サービス種別名 (例: "通所介護", "特別養護老人ホーム")
    staff: StaffInfo
    users: UserComposition
    current_status: CurrentStatus
    current_system: str = "未導入"        # カイポケ / ワイズマン / ほのぼの / ケアカルテ / 未導入 / その他
    point_value_yen: float = 10.00        # 1単位あたりの地域単価(円)。地域区分により10.00〜11.40円等
    service_days_per_month: int = 22      # 通所系等の平均月間提供日数
    base_monthly_billing_yen: float = 0.0  # 加算前の月間介護報酬総額(概算)。%型加算の計算に使用


# ---------------------------------------------------------------------------
# 加算マスタ(知識ベース)
# ---------------------------------------------------------------------------
@dataclass
class Requirement:
    key: str
    description: str
    check: Callable[[FacilityProfile], bool]


@dataclass
class CostItem:
    name: str
    amount_yen: float
    note: str = ""


@dataclass
class DifficultyFactors:
    staff_change_required: bool     # 新規採用/増員が必要か
    system_change_required: bool    # システム導入/改修が必要か
    documentation_load: int         # 書類作成負荷 1(軽)-5(重)
    lead_time_months: float         # 届出〜算定開始までの目安月数


@dataclass
class KasanDefinition:
    code: str
    name: str
    revision: str                     # 準拠する報酬改定 (例: "令和6年度(2024)介護報酬改定")
    service_categories: list           # 適用可能な業務形態 [ServiceCategory, ...]
    service_types: list                # 適用可能な具体的サービス種別。空リストならcategory内すべてに適用
    billing_basis: BillingBasis
    unit_points: float                 # 単位数。PERCENTAGE_OF_BILLINGの場合は加算率(%)
    target_user_selector: Callable[[UserComposition], int]
    requirements: list                 # list[Requirement]
    initial_cost_items: list           # list[Callable[[FacilityProfile], Optional[CostItem]]]
    running_cost_items: list           # list[Callable[[FacilityProfile], Optional[CostItem]]]
    difficulty: DifficultyFactors
    system_compatibility: dict         # {"カイポケ": "対応可", ...}
    roadmap_template: list             # list[str]
    notes: str = ""
