# システム要件（system_requirements）

機能ごとのシステム要件を本ディレクトリに配置する。

## 構成

| ファイル | 対応 BR | 内容 |
|----------|---------|------|
| [sr-00_partner_management.md](./sr-00_partner_management.md) | - | 取引先管理（SR-01〜SR-03 の前提） |
| [sr-01_gmail_invoice_ingest.md](./sr-01_gmail_invoice_ingest.md) | BR-01 | Gmail からの請求書取込・蓄積 |
| [sr-02_invoice_field_extraction.md](./sr-02_invoice_field_extraction.md) | BR-02 | 請求書からの必要項目の自動出力 |
| [sr-03_freee_payment_request.md](./sr-03_freee_payment_request.md) | BR-03、BR-04 | 支払い依頼の確認・freee への申請 |

## 記載方針

- 機能要件
  - 機能概要
  - 振る舞い
  - Output（データが関わる場合のみ）
- 非機能要件

振る舞いは解釈が分かれない形で書き、実装技術は指定しない。
