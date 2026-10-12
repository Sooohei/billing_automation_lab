# billing_automation_lab

広告配信代理業における、メディア請求書と事前申請の紐付け、および freee への支払い依頼作成支援の検証用リポジトリ。

Gmail からの請求書自動取込・蓄積、支払い依頼内容の自動入力、案件担当者による確認・送信。

## ドキュメント

| 文書 | 内容 |
|------|------|
| [業務要件](./docs/requirements/business_requirements.md) | 想定業務、As-Is / To-Be、スコープ |
| [システム要件](./docs/requirements/system_requirements/README.md) | 機能ごとのシステム要件 |
| [freee 連携の実現可能性調査](./docs/design/freee_feasibility.md) | システム要件が freee の仕様上実現できるかの確認結果 |
| [全体構成](./docs/design/architecture.md) | 全 SR 共通の技術スタック、Google Cloud・ローカルの構成、認証 |
| [SR-00 取引先管理 設計](./docs/design/sr-00_partner_management.md) | 取引先管理のデータモデル、入力チェック、画面 |
| [SR-01 Gmail からの請求書取込・蓄積 設計](./docs/design/sr-01_gmail_invoice_ingest.md) | 取込対象の判定、取込の流れ、Gmail への接続 |
| [SR-02 請求書からの必要項目の自動出力 設計](./docs/design/sr-02_invoice_field_extraction.md) | 1 時間ごとのバッチ、Gemini による読み取り、形式チェック |

## スコープ（要約）

**対象**

- Gmail からの請求書自動取込・蓄積
- 支払い前の請求書からの必要項目自動入力
- freee 支払い依頼申請用インプットの確定 UI
- 確定インプットにもとづく freee への支払い依頼作成

**対象外**

- 支払い依頼後の修正・再依頼・差し戻し対応
- ユーザーごとの情報の出し分け
- 経理による freee 上での支払い依頼確認・承認

## ステータス

システム要件の定義を完了し、設計フェーズに着手。実装未着手。freee とは通信せず、サンプルデータで検証する。
