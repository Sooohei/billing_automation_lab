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

取引先の登録から、Gmail からの請求書の取込、読み取り結果の確認・修正、freee への申請までを、ローカルで一通り試す手順。Gmail・Gemini・freee とは通信せず、`sample_data/` のサンプルデータを使う。

### 必要なもの

- Docker（PostgreSQL を動かす）
- [uv](https://docs.astral.sh/uv/)（Python 3.13 と依存パッケージを用意する）
- ブラウザ

### 1. 準備する（初回だけ）

```sh
uv sync                        # Python と依存パッケージを入れる
cp .env.example .env           # 設定ファイルを作る
docker compose up -d           # PostgreSQL を起動する（開発用の billing と、テスト用の billing_test の DB ができる）
uv run alembic upgrade head    # テーブルを作る
```

2 回目以降は、`docker compose up -d` で PostgreSQL を起動するだけでよい。

### 2. アプリを起動する

```sh
uv run uvicorn app.main:app --reload
```

ブラウザで http://localhost:8000/ を開くと、請求書一覧が表示される（まだ請求書はない）。ログインは省略しており、利用者は `dev@example.com` として扱われる。

### 3. 取引先を登録する（SR-00）

画面上部の「取引先管理」→「取引先を登録する」から、サンプルのメールの送信元にあたる次の 4 件を登録する。freee に申請するときの既定値は、どれを選んでもよい。

| 取引先名 | 送信元メールアドレス |
|----------|----------------------|
| Aメディア | `billing@a-media.jp` |
| Bネットワークス | `invoice@b-networks.jp` |
| Cアド | `info@c-ad.jp` |
| Dパブリッシング | `billing@d-publishing.jp` |

入力チェックも試せる。取引先名を空にする、別の取引先と同じアドレスを入れる、`@` のないアドレスを入れる、などで登録できないことと、そのメッセージを確かめられる。

### 4. 請求書を取り込む（SR-01・SR-02）

本来は 1 時間ごとに自動で動くバッチを、別のターミナルから手動で実行する。

```sh
uv run python -m app.jobs.hourly
```

次のように出れば成功。

```text
INFO [app.invoices.ingest] 取込が終わりました: 取り込んだメール=5 件、作成した請求書データ=5 件、失敗=0 件
INFO [app.extraction.extract] 抽出が終わりました: 作成した抽出結果=5 件、失敗=0 件
```

バッチは、`sample_data/gmail/` のサンプルのメール 8 通を Gmail の代わりに読み、取込の条件を満たすものから請求書データを作る（SR-01）。続けて、`sample_data/extraction/` のサンプルの読み取り結果を Gemini の代わりに使い、請求書ごとの抽出結果を作る（SR-02）。

| サンプルのメール | 取込の結果 | 読み取り結果 |
|------------------|------------|--------------|
| Aメディアから PDF 1 件 | 取り込む | すべての項目を読み取れる |
| Bネットワークスから PDF 2 件 | 2 件とも取り込む | 1 件目は税抜金額・消費税額が「読み取れず」、2 件目はすべて「読み取れず」 |
| Cアドから、ファイル名が `.PDF` の添付 | 取り込む | 全角・ハイフン付きの登録番号が `T` + 13 桁にそろう |
| Dパブリッシングから（アドレスに大文字を含む） | 取り込む | 支払期日と税込金額が「読み取れず」 |
| Aメディアから CSV の添付だけ | 取り込まない（PDF がない） | — |
| 登録していない送信元から | 取り込まない | — |
| 運用開始日（2026-10-01）より前に受信 | 取り込まない | — |
| Aメディアから、1 通目と同じ PDF の再送 | 請求書データを作らない（重複） | — |

もう一度実行しても、取込済みのメールは取り込まれない（「取り込んだメール=0 件」になる）。

### 5. 請求書一覧で確かめる（SR-03）

ブラウザで請求書一覧を再読み込みすると、取り込んだ 5 件が支払期日の古い順に並ぶ。支払期日が「読み取れず」の請求書は末尾に並ぶ。

- 受信日時・取引先・申請状態で絞り込める
- 11 件以上あるときは「次の 10 件を表示」ボタンが出る（サンプルは 5 件なので出ない）

### 6. 確認・修正して申請する（SR-03）

ここでは、読み取れなかった項目がある「Dパブリッシング」の請求書を例にする。

1. 一覧の「確認・修正」を押す。左に請求書の PDF、右に支払い依頼インプットが表示される。初めて開いたときに、読み取り結果と取引先の既定値から初期値が入る
2. 「読み取れず」の印が付いた支払期日と税込金額を、PDF を見ながら入力する（支払期日 `2026-11-15`、税込金額 `880000`）
3. 「紐付ける事前申請」の検索欄に「Dパブ」と入力して絞り込み、`A-0004` を選ぶ
4. 「保存」を押すと「保存しました」と表示される
5. 「申請」を押すと、freee への申請（サンプルなので必ず成功する）が行われ、「freee に支払い依頼を申請しました」と表示される。画面は読み取り専用になり、freee 支払い依頼の識別子・申請者・申請日時が表示される

申請できない場合の表示も試せる。たとえば、別の請求書で事前申請を選ばずに「申請」を押すと、空の必須項目と「紐付ける事前申請を選択してください」がまとめて表示され、申請されない。

事前申請のサンプル（`sample_data/freee/approval_requests.json`）は 10 件あり、紐付けの条件を満たす 5 件（`A-0001`〜`A-0004`、`A-0010`）だけが選択肢に出る。承認済みでないもの、件名に「媒体費」を含まないもの、作成済みの申請が 15 件に達したものなどは出ない。

### 7. 結果を確かめる

請求書一覧に戻り、申請状態を「申請済」で絞り込むと、申請した請求書だけが表示される。DB の中身を直接見る場合は次のようにする。

```sh
docker compose exec postgres psql -U app -d billing -c "SELECT status, freee_payment_request_id, applicant_email, applied_at FROM payment_request_inputs"
```

### 最初からやり直す

取引先・請求書などのデータと、保存した PDF を消す。

```sh
docker compose exec -T postgres psql -U app -d billing -c "TRUNCATE payment_request_inputs, extraction_results, invoices, ingested_messages, partner_emails, partners CASCADE"
rm -rf .local/storage/invoices
```

PostgreSQL ごと作り直す場合は `docker compose down -v` のあと、手順 1 の `docker compose up -d` と `uv run alembic upgrade head` をやり直す。

### テストとチェック

```sh
uv run pytest          # 自動テスト（テスト用の DB billing_test を使う。開発用の DB には触れない）
uv run ruff check      # Lint
uv run ruff format     # 整形
uv run mypy app        # 型チェック
```