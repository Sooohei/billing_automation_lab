# billing_automation_lab

広告配信代理業における、メディア請求書と事前申請の紐付け、および freee への支払い依頼作成支援の検証用リポジトリ。

Gmail からの請求書自動取込・蓄積、支払い依頼内容の自動入力、案件担当者による確認・送信。

## ドキュメント

| 文書 | 内容 |
|------|------|
| [業務要件](./docs/requirements/business_requirements.md) | 想定業務、As-Is / To-Be、スコープ |
| [システム要件](./docs/requirements/system_requirements/README.md) | 機能ごとのシステム要件 |
| [freee 連携の実現可能性調査](./docs/design/freee_feasibility.md) | システム要件が freee の仕様上実現できるかの確認結果 |
| [全体構成](./docs/design/architecture.md) | 全 SR 共通の技術スタック、ローカルの構成、Google Cloud にデプロイする場合の想定、認証 |
| [SR-00 取引先管理 設計](./docs/design/sr-00_partner_management.md) | 取引先管理のデータモデル、入力チェック、画面 |
| [SR-01 Gmail からの請求書取込・蓄積 設計](./docs/design/sr-01_gmail_invoice_ingest.md) | 取込対象の判定、取込の流れ、Gmail への接続 |
| [SR-02 請求書からの必要項目の自動出力 設計](./docs/design/sr-02_invoice_field_extraction.md) | 1 時間ごとのバッチ、読み取り、形式チェック |
| [SR-03 支払い依頼の確認・freee への申請 設計](./docs/design/sr-03_freee_payment_request.md) | 一覧画面、確認・修正画面、freee への申請 |

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

SR-00〜SR-03 をローカルで実装済み。

- Google Cloud 上で動かすことを前提に設計しているが、検証用（lab）のため、Google Cloud へのデプロイは行わない
- 外部のサービス（Gmail、Vertex AI の Gemini、freee）とは通信せず、`sample_data/` のサンプルデータで動かす


## ローカルでの動作確認方法

Docker だけで動かす。Gmail・Gemini・freee とは通信せず、`sample_data/` のサンプルデータを使う。

### 必要なもの

- Docker

### 1. 準備する（初回だけ）

```sh
docker compose --profile app build
```

ソースを変更したときも、もう一度実行する。

### 2. アプリを起動する

```sh
docker compose --profile app up -d
```

DB の準備（テーブルの作成）は、起動時に自動で行われる。

確認: http://localhost:8000/ を開くと請求書一覧が表示される。

### 3. 取引先を登録する（SR-00）

「取引先管理」→「取引先を登録する」から、次の 4 件を登録する（freee の既定値はどれでもよい）。

| 取引先名 | 送信元メールアドレス |
|----------|----------------------|
| Aメディア | `billing@a-media.jp` |
| Bネットワークス | `invoice@b-networks.jp` |
| Cアド | `info@c-ad.jp` |
| Dパブリッシング | `billing@d-publishing.jp` |

確認: 取引先管理の一覧に 4 件表示される。

### 4. 請求書を取り込む（SR-01・SR-02）

```sh
docker compose --profile app run --rm app python -m app.jobs.hourly
```

確認: 「作成した請求書データ=5 件」「作成した抽出結果=5 件」と表示される。

### 5. 請求書一覧で確かめる（SR-03）

確認: 請求書一覧を再読み込みすると、請求書が 5 件表示される。

### 6. 確認・修正して申請する（SR-03）

1. 一覧の「確認・修正」を押す
2. 空の項目を入力し、「紐付ける事前申請」を 1 件選ぶ
3. 「申請」を押す

確認: 「freee に支払い依頼を申請しました」と表示される。

### 7. 結果を確かめる

確認: 請求書一覧で、申請した請求書が「申請済」になっている。

### 止める

```sh
docker compose --profile app down
```

### 最初からやり直す

```sh
docker compose exec -T postgres psql -U app -d billing -c "TRUNCATE payment_request_inputs, extraction_results, invoices, ingested_messages, partner_emails, partners CASCADE"
rm -rf .local/storage/invoices
```
