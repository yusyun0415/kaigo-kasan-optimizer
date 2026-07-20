"""
加算マスタ(サンプルデータ)

【重要】本マスタの単位数・要件は令和6年度(2024年度)介護報酬改定を基にした代表例です。
  - 地域区分による単価差、その後のQ&A・軽微な告示改正までは反映していません。
  - 本番運用時は、厚生労働省の告示・通知および国保連の最新資料と必ず突合してください。
  - ここでの目的は「加算提案アルゴリズムのロジック」を具体的に検証できる形で示すことです。
"""

from models import (
    ServiceCategory as SC,
    BillingBasis as BB,
    KasanDefinition,
    Requirement,
    CostItem,
    DifficultyFactors,
)

REVISION = "令和6年度(2024)介護報酬改定"


def _no_cost(profile):
    return None


# ---------------------------------------------------------------------------
# 共通系(複数サービス類型に横断的に存在)
# ---------------------------------------------------------------------------

KASAN_SCIENCE_1 = KasanDefinition(
    code="SCIENCE_1",
    name="科学的介護推進体制加算(I)",
    revision=REVISION,
    service_categories=[SC.FACILITY, SC.DAYCARE, SC.OTHER],
    service_types=[],
    billing_basis=BB.PER_USER_PER_MONTH,
    unit_points=40,
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement(
            "life_submission",
            "LIFE(科学的介護情報システム)へ利用者ごとの情報を提出し、フィードバックを活用する体制がある",
            lambda p: True,  # 体制構築の有無は入力次第。ここでは要件充足チェックの対象外(要件クリアの手順で案内)
        ),
    ],
    initial_cost_items=[
        lambda p: CostItem("LIFE入力・運用フロー整備(初期設定・職員教育)", 50000, "既存システムがLIFE対応CSV出力に対応していれば低コスト"),
    ],
    running_cost_items=[
        lambda p: CostItem("LIFEへの定期データ入力工数(年間、概算人件費換算)", 240000, "入力担当者の業務時間を人件費換算(四半期提出想定)"),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=True,
                                  documentation_load=2, lead_time_months=1),
    system_compatibility={
        "カイポケ": "対応可(LIFE連携機能あり)",
        "ワイズマン": "対応可(LIFE連携機能あり)",
        "ほのぼの": "対応可(LIFE連携機能あり)",
        "ケアカルテ": "対応可(LIFE連携機能あり)",
        "未導入": "手動でLIFEへCSVアップロードする運用を構築する必要あり",
    },
    roadmap_template=[
        "利用者ごとのADL・栄養・口腔等のアセスメント項目をLIFE提出様式に合わせて整備する",
        "3ヶ月に1回以上の頻度でLIFEへ情報提出する運用フローを確立する",
        "フィードバック票を職員間で共有し、ケアプラン・計画書へ反映する体制を作る",
        "体制等状況一覧表を保険者へ届出する",
    ],
    notes="LIFE提出とフィードバック活用が全ての起点となる加算。他の多くの加算(自立支援促進加算等)の前提条件にもなる。",
)

KASAN_TREATMENT_IMPROVEMENT = KasanDefinition(
    code="TREATMENT_IMPROVEMENT",
    name="介護職員等処遇改善加算",
    revision=REVISION,
    service_categories=[SC.FACILITY, SC.DAYCARE, SC.HOMEVISIT, SC.OTHER],
    service_types=[],
    billing_basis=BB.PERCENTAGE_OF_BILLING,
    unit_points=6.0,  # サービス類型・区分(I~IV)により大きく異なる。ここでは通所系(区分II相当)の概算値
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement(
            "wage_improvement_plan",
            "賃金改善計画を作成し、職員に周知した上で保険者へ届出している",
            lambda p: True,
        ),
        Requirement(
            "career_path_requirement",
            "キャリアパス要件(資格・経験に応じた昇給の仕組み等)を満たしている",
            lambda p: True,
        ),
    ],
    initial_cost_items=[
        lambda p: CostItem("就業規則・賃金規程の改定(社労士費用目安)", 150000, "賃金体系の見直しが必要な場合"),
    ],
    running_cost_items=[
        lambda p: CostItem("職員への賃金改善原資(加算収益のほぼ全額を職員へ配分する必要あり)", 0,
                            "加算収益は要件上ほぼ全額を賃金改善に充てる必要があるため、施設の実質的な純利益にはならない点に留意"),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=4, lead_time_months=2),
    system_compatibility={
        "カイポケ": "対応可(処遇改善計画書テンプレートあり)",
        "ワイズマン": "対応可",
        "ほのぼの": "対応可",
        "ケアカルテ": "要確認",
        "未導入": "様式は厚労省HPから入手可能",
    },
    roadmap_template=[
        "賃金改善計画書を作成する(いつ・誰に・どう配分するか)",
        "就業規則等にキャリアパス要件(職位・職責・職務内容に応じた任用要件と賃金体系)を明記する",
        "職員会議等で計画内容を周知する",
        "都道府県・市区町村へ処遇改善計画書を届出する",
        "実績報告書を翌年度に提出する",
    ],
    notes="収益額は大きいが、加算原資は原則として職員の賃金改善に充当する必要があり、"
          "『施設の利益』としてではなく『職員定着・採用力向上への投資』として費用対効果を評価すべき加算。",
)


# ---------------------------------------------------------------------------
# 施設型
# ---------------------------------------------------------------------------

KASAN_ADL_MAINTAIN_1 = KasanDefinition(
    code="ADL_MAINTAIN_1_FACILITY",
    name="ADL維持等加算(I)",
    revision=REVISION,
    service_categories=[SC.FACILITY],
    service_types=[],
    billing_basis=BB.PER_USER_PER_MONTH,
    unit_points=30,
    target_user_selector=lambda u: u.care_only_users,
    requirements=[
        Requirement("life_base", "科学的介護推進体制加算相当のLIFEデータ提出を行っている", lambda p: True),
        Requirement("adl_measurement", "Barthel Indexを用いたADL評価を6ヶ月に1回以上実施している", lambda p: True),
    ],
    initial_cost_items=[_no_cost],
    running_cost_items=[
        lambda p: CostItem("ADL評価(Barthel Index)実施の人件費(年間、半年毎2回分)", 60000, "既存職員による実施を想定"),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=True,
                                  documentation_load=2, lead_time_months=2),
    system_compatibility={
        "カイポケ": "対応可(ADL評価入力機能あり)",
        "ワイズマン": "対応可",
        "ほのぼの": "要確認(バージョンによる)",
        "ケアカルテ": "対応可",
        "未導入": "Excel等での評価記録管理が必要",
    },
    roadmap_template=[
        "全入所者に対しBarthel Indexによる評価を6ヶ月間隔で実施する体制を作る",
        "評価データをLIFEへ提出する",
        "評価対象者の一定割合以上でADLの維持・改善が確認できることを確認する(実績要件)",
    ],
    notes="ADLの利得(改善度)実績が要件に影響するため、リハ職との連携が鍵。",
)

KASAN_NUTRITION_MGMT = KasanDefinition(
    code="NUTRITION_MGMT_STRENGTH",
    name="栄養マネジメント強化加算",
    revision=REVISION,
    service_categories=[SC.FACILITY],
    service_types=[],
    billing_basis=BB.PER_USER_PER_DAY,
    unit_points=11,
    target_user_selector=lambda u: u.care_only_users,
    requirements=[
        Requirement(
            "dietitian_staffing",
            "常勤換算で入所者50人あたり1人以上の管理栄養士(またはこれに準ずる配置)を置いている",
            lambda p: p.staff.dietitian_count >= 1,
        ),
        Requirement("low_weight_screening", "低栄養リスクの高い利用者に対し必要な栄養ケアを個別に実施している", lambda p: True),
    ],
    initial_cost_items=[
        lambda p: (CostItem("管理栄養士 採用費(求人広告・紹介手数料)", 300000, "未配置の場合")
                   if p.staff.dietitian_count == 0 else None),
    ],
    running_cost_items=[
        lambda p: (CostItem("管理栄養士 人件費(常勤1名 年収ベース)", 4200000, "未配置からの新規常勤雇用を想定")
                   if p.staff.dietitian_count == 0 else None),
    ],
    difficulty=DifficultyFactors(staff_change_required=True, system_change_required=False,
                                  documentation_load=3, lead_time_months=3),
    system_compatibility={
        "カイポケ": "対応可(栄養ケア計画書テンプレートあり)",
        "ワイズマン": "対応可",
        "ほのぼの": "対応可",
        "ケアカルテ": "対応可",
        "未導入": "栄養ケア計画書の様式整備が必要",
    },
    roadmap_template=[
        "管理栄養士の配置(採用または委託契約)を確保する",
        "入所者ごとに栄養スクリーニング・栄養ケア計画を作成する",
        "低栄養リスク者に対するモニタリングを定期実施する体制を作る",
    ],
    notes="管理栄養士が未配置の施設では、人件費が加算収益を上回り赤字になりやすい代表例。"
          "利用者数が少ない施設では非常勤・外部委託の活用を検討すべき。",
)

KASAN_DEMENTIA_CARE_1 = KasanDefinition(
    code="DEMENTIA_CARE_1",
    name="認知症専門ケア加算(I)",
    revision=REVISION,
    service_categories=[SC.FACILITY, SC.DAYCARE, SC.OTHER],
    service_types=[],
    billing_basis=BB.PER_USER_PER_DAY,
    unit_points=3,
    target_user_selector=lambda u: round(u.total_users * u.dementia_high_ratio),
    requirements=[
        Requirement(
            "dementia_ratio",
            "日常生活自立度III以上の認知症利用者が利用者総数の半数以上を占める",
            lambda p: p.users.dementia_high_ratio >= 0.5,
        ),
        Requirement(
            "specialist_training",
            "認知症介護実践リーダー研修等を修了した職員を配置している",
            lambda p: True,
        ),
    ],
    initial_cost_items=[
        lambda p: CostItem("認知症介護実践リーダー研修 受講費", 60000, "対象職員が未受講の場合(1名あたり)"),
    ],
    running_cost_items=[_no_cost],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=2, lead_time_months=4),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "対応可", "ケアカルテ": "対応可",
        "未導入": "研修修了証等の管理台帳を別途整備",
    },
    roadmap_template=[
        "認知症介護実践リーダー研修修了者を1名以上配置する(研修は自治体・都道府県主催、数ヶ月待ちのことが多い)",
        "認知症ケアに関する会議を定期開催し、記録を残す",
        "体制等状況一覧表を保険者へ届出する",
    ],
    notes="研修の開催頻度・定員により受講までのリードタイムが長くなりやすい点に注意。",
)


# ---------------------------------------------------------------------------
# 通所型
# ---------------------------------------------------------------------------

KASAN_KOBETSU_KINOU_1 = KasanDefinition(
    code="KOBETSU_KINOU_1",
    name="個別機能訓練加算(I)",
    revision=REVISION,
    service_categories=[SC.DAYCARE],
    service_types=[],
    billing_basis=BB.PER_USER_PER_DAY,
    unit_points=56,
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement(
            "function_trainer",
            "専従の機能訓練指導員(PT/OT/ST/看護師/柔整師等)を配置している",
            lambda p: p.staff.rehab_staff_count >= 1,
        ),
        Requirement("individual_plan", "利用者ごとの個別機能訓練計画を作成し、居宅訪問等でアセスメントしている", lambda p: True),
    ],
    initial_cost_items=[
        lambda p: (CostItem("機能訓練指導員 採用費", 250000, "PT/OT/ST等が未配置の場合") if p.staff.rehab_staff_count == 0 else None),
    ],
    running_cost_items=[
        lambda p: (CostItem("機能訓練指導員 人件費(非常勤 週20h想定)", 2200000, "未配置からの新規雇用を想定")
                   if p.staff.rehab_staff_count == 0 else None),
    ],
    difficulty=DifficultyFactors(staff_change_required=True, system_change_required=False,
                                  documentation_load=3, lead_time_months=2),
    system_compatibility={
        "カイポケ": "対応可(機能訓練計画書テンプレートあり)",
        "ワイズマン": "対応可", "ほのぼの": "対応可", "ケアカルテ": "対応可",
        "未導入": "個別機能訓練計画書の様式整備が必要",
    },
    roadmap_template=[
        "機能訓練指導員(専従1名以上)を確保する",
        "利用者宅を訪問し、生活環境を踏まえた個別機能訓練計画を作成する",
        "3ヶ月に1回以上、計画の見直し(モニタリング)を行う",
    ],
    notes="単価が高く収益貢献は大きいが、専門職の新規配置が前提となるため人件費インパクトも大きい。",
)

KASAN_NUTRITION_ASSESS = KasanDefinition(
    code="NUTRITION_ASSESS",
    name="栄養アセスメント加算",
    revision=REVISION,
    service_categories=[SC.DAYCARE],
    service_types=[],
    billing_basis=BB.PER_USER_PER_MONTH,
    unit_points=50,
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement(
            "dietitian_access",
            "管理栄養士を配置している、または外部(他事業所・栄養ケア・ステーション等)の管理栄養士と連携している",
            lambda p: p.staff.dietitian_count >= 1 or p.staff.dietitian_external_partnership,
        ),
    ],
    initial_cost_items=[
        lambda p: (CostItem("外部管理栄養士との連携契約 初期費用", 50000, "外部連携を新規に契約する場合")
                   if (p.staff.dietitian_count == 0 and not p.staff.dietitian_external_partnership) else None),
    ],
    running_cost_items=[
        lambda p: (CostItem("外部管理栄養士連携 委託費(年額、月3万円想定)", 360000, "常勤雇用ではなく外部連携で対応する場合の年額")
                   if (p.staff.dietitian_count == 0 and not p.staff.dietitian_external_partnership) else None),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=2, lead_time_months=1),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "対応可", "ケアカルテ": "対応可",
        "未導入": "栄養アセスメント様式の整備が必要",
    },
    roadmap_template=[
        "管理栄養士(常勤/非常勤/外部連携)を確保する",
        "利用者ごとに栄養状態のアセスメントを実施し、多職種で共有する",
        "3ヶ月に1回以上、アセスメントを見直す",
    ],
    notes="常勤雇用ではなく外部の管理栄養士との連携(委託)で要件を満たせるため、"
          "栄養マネジメント強化加算(施設向け)に比べて低コストで取得しやすい。",
)

KASAN_ORAL_NUTRITION_SCREENING = KasanDefinition(
    code="ORAL_NUTRITION_SCREENING_1",
    name="口腔・栄養スクリーニング加算(I)",
    revision=REVISION,
    service_categories=[SC.DAYCARE],
    service_types=[],
    billing_basis=BB.PER_USER_PER_MONTH,
    unit_points=3.3,  # 20単位/6ヶ月を月割りした概算値
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement("screening_flow", "6ヶ月に1回以上、口腔状態・栄養状態のスクリーニングを実施し記録している", lambda p: True),
    ],
    initial_cost_items=[_no_cost],
    running_cost_items=[
        lambda p: CostItem("スクリーニング実施・記録の人件費(既存職員で対応)", 20000, "追加雇用不要な想定"),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=1, lead_time_months=1),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "対応可", "ケアカルテ": "対応可",
        "未導入": "チェックシート様式のみで運用可能",
    },
    roadmap_template=[
        "既存の相談員・介護職員が実施できるスクリーニングシートを整備する",
        "6ヶ月に1回以上のスクリーニングを実施・記録する",
        "リスクが確認された利用者は栄養アセスメント加算等へつなげる",
    ],
    notes="追加人員がほぼ不要で、既存職員の運用調整のみで取得できる代表的な『低難易度』加算。",
)

KASAN_MID_HEAVY_CARE = KasanDefinition(
    code="MID_HEAVY_CARE",
    name="中重度者ケア体制加算",
    revision=REVISION,
    service_categories=[SC.DAYCARE],
    service_types=["通所介護"],
    billing_basis=BB.PER_USER_PER_DAY,
    unit_points=45,
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement(
            "nurse_staffing",
            "看護職員を通常の人員基準に加えて1名以上多く配置している",
            lambda p: p.staff.nurses_ftk >= 1.0,
        ),
        Requirement(
            "mid_heavy_ratio",
            "要介護3〜5の利用者が利用者total数の30%以上を占める",
            lambda p: (p.users.mid_to_heavy_users / max(p.users.total_users, 1)) >= 0.3,
        ),
    ],
    initial_cost_items=[
        lambda p: (CostItem("看護職員 採用費", 300000, "増員が必要な場合") if p.staff.nurses_ftk < 1.0 else None),
    ],
    running_cost_items=[
        lambda p: (CostItem("看護職員 人件費(常勤換算1名 増員分)", 4500000, "増員が必要な場合")
                   if p.staff.nurses_ftk < 1.0 else None),
    ],
    difficulty=DifficultyFactors(staff_change_required=True, system_change_required=False,
                                  documentation_load=2, lead_time_months=3),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "対応可", "ケアカルテ": "対応可",
        "未導入": "人員配置記録の管理体制が必要",
    },
    roadmap_template=[
        "看護職員を基準人員に加えて1名以上増配置する",
        "喀痰吸引等が必要な利用者の受入体制を整備する",
        "体制等状況一覧表を保険者へ届出する",
    ],
    notes="利用者の要介護度構成(中重度者比率)が要件に直結するため、対象者が少ない施設では収益効果が限定的。",
)


# ---------------------------------------------------------------------------
# 訪問型
# ---------------------------------------------------------------------------

KASAN_TOKUTEI_JIGYOSHO_2 = KasanDefinition(
    code="TOKUTEI_JIGYOSHO_2",
    name="特定事業所加算(II)",
    revision=REVISION,
    service_categories=[SC.HOMEVISIT],
    service_types=["訪問介護"],
    billing_basis=BB.PERCENTAGE_OF_BILLING,
    unit_points=10.0,
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement("training_system", "全ての訪問介護員に対する研修計画を策定し、実施している", lambda p: True),
        Requirement(
            "certified_ratio",
            "介護福祉士の割合が30%以上、または実務者研修修了者を含め50%以上",
            lambda p: p.staff.care_worker_certified_ratio >= 0.3,
        ),
        Requirement("case_conference", "定期的な会議(サービス担当者会議等)を月1回以上開催している", lambda p: True),
    ],
    initial_cost_items=[_no_cost],
    running_cost_items=[
        lambda p: CostItem("研修計画の実施・会議運営コスト(年間)", 150000, "既存職員の時間を人件費換算"),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=4, lead_time_months=2),
    system_compatibility={
        "カイポケ": "対応可(研修記録・会議記録テンプレートあり)",
        "ワイズマン": "対応可", "ほのぼの": "要確認", "ケアカルテ": "要確認",
        "未導入": "研修計画書・会議録の様式整備が必要",
    },
    roadmap_template=[
        "年間研修計画を策定し、全訪問介護員へ周知・実施する",
        "サービス提供責任者を中心とした定期会議を月1回以上開催し議事録を残す",
        "介護福祉士等の資格保有状況を集計し、要件充足を確認する",
        "体制等状況一覧表を保険者へ届出する",
    ],
    notes="人員基準要件よりも『運営体制の書類・記録整備』が中心のため、既存人員のまま取得できる可能性が高い。",
)

KASAN_EMERGENCY_VISIT = KasanDefinition(
    code="EMERGENCY_VISIT",
    name="緊急時訪問介護加算",
    revision=REVISION,
    service_categories=[SC.HOMEVISIT],
    service_types=["訪問介護"],
    billing_basis=BB.PER_VISIT,
    unit_points=100,
    target_user_selector=lambda u: max(round(u.total_users * 0.1), 0),  # 緊急訪問対象は利用者の一部と仮定
    requirements=[
        Requirement("on_call_system", "利用者・ケアマネからの要請に24時間対応できる体制(オンコール等)を整備している", lambda p: True),
    ],
    initial_cost_items=[
        lambda p: CostItem("オンコール携帯・体制整備費", 30000, ""),
    ],
    running_cost_items=[
        lambda p: CostItem("緊急対応手当(オンコール当番手当、年間概算)", 240000, ""),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=2, lead_time_months=1),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "対応可", "ケアカルテ": "対応可",
        "未導入": "緊急訪問記録の管理体制が必要",
    },
    roadmap_template=[
        "24時間連絡が取れる体制(オンコール担当のローテーション)を構築する",
        "緊急時訪問の記録(要請日時・内容・対応)を残す運用にする",
        "利用者・ケアマネへ緊急時対応の周知を行う",
    ],
    notes="算定回数は突発的な要請に依存するため、収益は保守的に見積もるべき。",
)

KASAN_HOMONKANGO_EMERGENCY = KasanDefinition(
    code="HOMONKANGO_EMERGENCY",
    name="緊急時訪問看護加算(I)",
    revision=REVISION,
    service_categories=[SC.HOMEVISIT],
    service_types=["訪問看護"],
    billing_basis=BB.PER_USER_PER_MONTH,
    unit_points=574,
    target_user_selector=lambda u: u.total_users,
    requirements=[
        Requirement(
            "nurse_oncall",
            "看護職員が24時間連絡を受け、必要な場合に訪問できる体制を確保している",
            lambda p: p.staff.nurses_ftk >= 1.0,
        ),
    ],
    initial_cost_items=[
        lambda p: (CostItem("看護職員 採用費", 300000, "1名も配置がない場合") if p.staff.nurses_ftk < 1.0 else None),
    ],
    running_cost_items=[
        lambda p: CostItem("オンコール当番手当(看護職員、年間概算)", 360000, ""),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=2, lead_time_months=1),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "要確認", "ケアカルテ": "対応可",
        "未導入": "オンコール記録の管理体制が必要",
    },
    roadmap_template=[
        "看護職員による24時間対応体制(オンコール)を構築する",
        "利用者・主治医への説明と同意取得を行う",
        "緊急時訪問看護の実施記録を整備する",
    ],
    notes="訪問看護は単価が高く、看護師が既に1名以上いる事業所では追加投資なしで取得できる代表例。",
)

KASAN_TOKUBETSU_KANRI_1 = KasanDefinition(
    code="TOKUBETSU_KANRI_1",
    name="特別管理加算(I)",
    revision=REVISION,
    service_categories=[SC.HOMEVISIT],
    service_types=["訪問看護"],
    billing_basis=BB.PER_USER_PER_MONTH,
    unit_points=500,
    target_user_selector=lambda u: round(u.total_users * u.medical_dependency_ratio),
    requirements=[
        Requirement(
            "medical_dependency",
            "気管切開・人工呼吸器管理等、医療依存度の高い利用者が一定数存在する",
            lambda p: p.users.medical_dependency_ratio > 0,
        ),
    ],
    initial_cost_items=[_no_cost],
    running_cost_items=[
        lambda p: CostItem("医療材料・特殊ケア対応の研修費(年間概算)", 80000, ""),
    ],
    difficulty=DifficultyFactors(staff_change_required=False, system_change_required=False,
                                  documentation_load=2, lead_time_months=1),
    system_compatibility={
        "カイポケ": "対応可", "ワイズマン": "対応可", "ほのぼの": "要確認", "ケアカルテ": "対応可",
        "未導入": "医療処置記録の管理体制が必要",
    },
    roadmap_template=[
        "対象となる医療依存度の高い利用者を特定し、主治医と連携した看護計画を作成する",
        "特別な医療処置に対応できるよう職員研修を実施する",
        "月の看護記録に処置内容を明記する",
    ],
    notes="対象者(医療依存度の高い利用者)がいなければ算定できないため、利用者構成に強く依存する。",
)


ALL_KASAN = [
    KASAN_SCIENCE_1,
    KASAN_TREATMENT_IMPROVEMENT,
    KASAN_ADL_MAINTAIN_1,
    KASAN_NUTRITION_MGMT,
    KASAN_DEMENTIA_CARE_1,
    KASAN_KOBETSU_KINOU_1,
    KASAN_NUTRITION_ASSESS,
    KASAN_ORAL_NUTRITION_SCREENING,
    KASAN_MID_HEAVY_CARE,
    KASAN_TOKUTEI_JIGYOSHO_2,
    KASAN_EMERGENCY_VISIT,
    KASAN_HOMONKANGO_EMERGENCY,
    KASAN_TOKUBETSU_KANRI_1,
]
