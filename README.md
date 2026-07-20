# 介護報酬加算 最適化提案ツール

介護施設の基本情報(業務形態・人員配置・利用者構成・現有加算・現有システム)から、獲得可能な介護報酬加算を「費用対効果」と「獲得難易度」の2軸で分析し、①費用対効果ランキング ②コスト見積もり ③獲得ロードマップ ④獲得容易性ランキング を出力するロジック/ツール一式。

対象改定基準: 令和6年度(2024年度)介護報酬改定。単位数・要件はロジック提示用の代表値であり、実運用前に最新の告示・単価表での検証が必要です。

## 構成

このリポジトリには、同じ設計思想を異なる形で実装した2系統が入っています。

| フォルダ | 内容 |
|---|---|
| [web-app/](web-app/) | ブラウザで完結する対話型HTML/JSツール。フォーム入力→即座に①〜④を算出する `kasan_app.html`、設計ロジックと計算例をまとめた `kasan_report.html` |
| [python-engine/](python-engine/) | Pythonでの参照実装。単一ファイル版の `kasan_engine.py` と、より作り込まれた多ファイル構成のプロトタイプ [care_kasan_advisor/](python-engine/care_kasan_advisor/) |

## 使い方

- **Webアプリ**: `web-app/kasan_app.html` をブラウザで開くだけで動作します(インストール不要)。
- **Python版(単一ファイル)**: `python python-engine/kasan_engine.py`
- **Python版(多ファイル)**: `python python-engine/care_kasan_advisor/demo.py`(詳細は [care_kasan_advisor/README.md](python-engine/care_kasan_advisor/README.md))

## 注意事項

- 加算マスタは代表的なサンプルのみを収録しており、全加算を網羅したものではありません。
- 本ツールは算定可否を保証するものではなく、設計ロジックの提示を目的とした参考資料です。実際の算定にあたっては指定権者(都道府県・市町村)への確認や専門家への相談を推奨します。
