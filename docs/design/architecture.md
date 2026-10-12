# 全体構成（architecture）

全 SR に共通する基盤の設計をまとめる。各 SR に固有の内容は、各 SR の設計書に書く。

## 方針

- 最終的には Google Cloud 上で動かすが、まずローカルですべての機能を試せる構成にする
- ローカルと Google Cloud の差は、環境変数で切り替える設定値だけにする
- freee とは通信しない。freee から取得するデータはサンプルデータで代替する（[freee 連携の実現可能性調査](./freee_feasibility.md)）

## 技術スタック

| 項目 | 採用 |
|------|------|
| 言語 | Python 3.13 |
| パッケージ管理 | uv（`pyproject.toml`、`uv.lock`、`.python-version`） |
| Web フレームワーク | FastAPI |
| 画面 | Jinja2 テンプレートによるサーバーサイド描画。部分的な画面の更新に htmx を使う（SR-03） |
| DB | PostgreSQL |
| DB アクセス | SQLAlchemy |
| マイグレーション | Alembic |
| テスト | pytest |
| 整形・Lint | Ruff |
| 型チェック | mypy |

## 開発環境

| 操作 | コマンド |
|------|----------|
| 依存関係のインストール | `uv sync` |
| PostgreSQL の起動 | `docker compose up -d` |
| マイグレーション | `uv run alembic upgrade head` |
| Web アプリの起動 | `uv run uvicorn app.main:app --reload` |
| 1 時間ごとのバッチの実行 | `uv run python -m app.jobs.hourly` |
| テスト | `uv run pytest` |
| 整形 | `uv run ruff format` |
| Lint | `uv run ruff check` |
| 型チェック | `uv run mypy app` |

各 SR の設計書の「ローカルでの試し方」に書いたコマンドも、`uv run` を付けて実行する。

### テスト

- 部分一意インデックス、advisory lock、`SELECT ... FOR UPDATE` など PostgreSQL の機能に頼るので、テストも PostgreSQL で行う（SQLite は使わない）
- `docker compose` の PostgreSQL に、開発用の DB（`billing`）とは別にテスト用の DB（`billing_test`）を作る。テストは `TEST_DATABASE_URL` の DB を使う
- テストの開始時に、テスト用の DB にマイグレーションを適用する。各テストの前に全テーブルを空にする
- 外部とのやり取り（`GmailClient`、`InvoiceExtractor`、`FreeeClient`）は、テスト用の偽物に差し替える。`FileStorage` は一時フォルダを使う `LocalFileStorage` にする

## 日時の扱い

| 対象 | 扱い |
|------|------|
| 日時（受信日時、取込日時、申請日時など） | DB には `timestamptz` で持つ（UTC で保存される） |
| 日付（請求書発行日、支払期日など） | DB には `date` で持つ。時差を考えない |
| 画面の表示 | 日時は日本時間（`Asia/Tokyo`）で `YYYY-MM-DD HH:MM` と表示する |
| 日付の判定 | 運用開始日（SR-01）、申請月（SR-03）、受信日時の絞り込み（SR-03）など、日付で区切る判定はすべて日本時間で行う |

## 画面の共通部分

- すべての画面で共通のレイアウト（`templates/base.html`）を使う。上部のメニューに「請求書一覧」（`/invoices`）と「取引先管理」（`/partners`）へのリンクと、ログインしている利用者のメールアドレスを表示する
- エラーの画面:

| 状態 | 表示 |
|------|------|
| 存在しない請求書・取引先を開いた（404） | 「お探しのページは見つかりません」と、請求書一覧へのリンク |
| CSRF 対策で拒否した（403） | 「この操作は受け付けられません。画面を開き直してください」 |
| 想定外のエラー（500） | 「エラーが発生しました」。エラーの詳細は画面に出さず、ログに出す |

## CSRF 対策

保存・申請・削除などの POST は、別のサイトから勝手に送らせる攻撃（CSRF）を防ぐため、`Origin` ヘッダーを確認する（ユーザー確認済み）。

- POST のリクエストで、`Origin` ヘッダーが `APP_ORIGIN` と一致しない、または `Origin` ヘッダーがない場合は、403 で拒否する
- すべての POST に共通の処理（FastAPI のミドルウェア）で行う
- GET では状態を変えない。ただし SR-03 の確認・修正画面は、開いたときに支払い依頼インプットを作る（要件 14）。これは同じ請求書に 1 回だけ初期値で作るもので、利用者の入力を書き換えないため、GET のままとする

## ログ

- ログは標準出力に出す。Google Cloud 上では Cloud Logging に集まる
- エラーのログには、対象の ID（請求書 ID、Gmail 上のメールの ID など）を含める
- 認証情報、請求書の中身はログに出さない

## 構成

### Google Cloud

```mermaid
flowchart LR
    User[利用者のブラウザ] --> IAP[Identity-Aware Proxy<br>Google ログイン]
    IAP --> Run[Cloud Run<br>Web アプリ]
    Run --> SQL[(Cloud SQL<br>PostgreSQL)]
    Run --> GCS[(Cloud Storage<br>請求書ファイル)]
    Scheduler[Cloud Scheduler] --> Job[Cloud Run Jobs<br>取込・抽出バッチ]
    Job --> SQL
    Job --> GCS
    Job --> Gmail[Gmail API]
    Job --> Gemini[Vertex AI<br>Gemini]
    Run -.-> Secret[Secret Manager]
    Job -.-> Secret
```

- Web アプリ（SR-00、SR-03 の画面）は Cloud Run のサービス 1 つとして動かす。利用者のアクセスは IAP を通す（[認証](#認証)）
- SR-01 の取込と SR-02 の抽出は、1 時間ごとの 1 つのバッチとして Cloud Run Jobs と Cloud Scheduler で動かす（[SR-02 の設計](./sr-02_invoice_field_extraction.md#1-時間ごとのバッチ)）
- 請求書 PDF からの項目の読み取りには、Vertex AI の Gemini を使う（[SR-02 の設計](./sr-02_invoice_field_extraction.md)）
- Cloud Run から Cloud SQL へは Cloud SQL Auth Proxy（Cloud Run の Cloud SQL 接続設定）で接続する
- Web アプリの Cloud Run の最小インスタンス数は 0 とし、使われていない間は課金されないようにする。起動を速くするため、起動時の CPU ブーストを有効にする（[制約](#制約)）
- 請求書ファイル（PDF）は Cloud Storage に保存する（[ファイル保存](#ファイル保存)）
- 秘匿情報（DB のパスワード、Gmail の認証情報、将来の freee の認証情報）は Secret Manager に置き、環境変数またはファイルとしてアプリに渡す

### ローカル

```mermaid
flowchart LR
    User[ブラウザ] --> App[uvicorn<br>Web アプリ]
    Cmd[コマンド実行] --> Batch[取込・抽出バッチ]
    App --> PG[(Docker の PostgreSQL)]
    Batch --> PG
    App --> Files[(ローカルのフォルダ<br>.local/storage/)]
    Batch --> Files
    App --> Sample[サンプルデータ<br>sample_data/]
    Batch --> Sample
    Batch -.-> Gmail[Gmail API<br>第 2 段階で実装]
    Batch -.-> Gemini[Vertex AI Gemini<br>第 2 段階で実装]
```

- PostgreSQL は `docker compose` で起動する
- アプリは `uvicorn` で起動する。取込・抽出バッチはコマンドで手動実行する
- Gmail は、最終的には実際の Gmail に接続する。実装は、サンプルのメールを返す形を先に作り、Gmail API との連携を後から作る（[Gmail 連携](#gmail-連携)）
- 請求書 PDF からの項目の読み取りも同じく、サンプルの結果を返す形を先に作り、Vertex AI の Gemini との連携を後から作る（[SR-02 の設計](./sr-02_invoice_field_extraction.md)）
- 秘匿情報は `.env` と `.local/`（どちらも Git 管理外）に置く。`.env.example` に項目だけを記載する

## 設定値

環境変数で渡す。

| 環境変数 | 内容 | ローカルの例 |
|----------|------|--------------|
| `DATABASE_URL` | DB の接続先 | `postgresql+psycopg://app:app@localhost:5432/billing` |
| `TEST_DATABASE_URL` | テスト用の DB の接続先 | `postgresql+psycopg://app:app@localhost:5432/billing_test` |
| `APP_ORIGIN` | Web アプリのオリジン（CSRF 対策で `Origin` ヘッダーと比べる） | `http://localhost:8000` |
| `AUTH_MODE` | 認証方式の切替。ローカルは `dev`、Google Cloud は `iap` | `dev` |
| `GMAIL_TOKEN_FILE` | Gmail の認証情報（OAuth クライアントとリフレッシュトークン）のファイルの場所。Gmail との外部連携（第 2 段階）から使う | `.local/gmail_token.json` |
| `STORAGE_BACKEND` | ファイル保存先の切替。`local` または `gcs` | `local` |
| `LOCAL_STORAGE_DIR` | `STORAGE_BACKEND=local` のときの保存先フォルダ | `.local/storage` |
| `GCS_BUCKET` | `STORAGE_BACKEND=gcs` のときのバケット名 | （ローカルでは使わない） |
| `INGEST_START_DATE` | SR-01 の運用開始日（`YYYY-MM-DD`、日本時間） | `2026-10-01` |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI を呼ぶ Google Cloud プロジェクト。Gemini との連携（第 2 段階）から使う | （要確認） |
| `VERTEX_AI_LOCATION` | Vertex AI のロケーション。第 2 段階から使う | （要確認） |
| `GEMINI_MODEL` | 使う Gemini のモデル名。第 2 段階から使う | （要確認） |

## freee 連携

freee とのやり取りは `FreeeClient` インターフェースに閉じ込める。本リポジトリでは、サンプルデータを返す `SampleFreeeClient` だけを実装する。実接続の実装は作らないので、実装の切替の設定値は設けない。インターフェースは、実接続に切り替えるときの差し替え口として残す。

| メソッド | 返す値 | 使う SR |
|----------|--------|---------|
| `list_partners()` | freee 上の取引先の一覧 | SR-00、SR-03 |
| `list_account_items()` | 勘定科目の一覧 | SR-00、SR-03 |
| `list_taxes()` | 税区分の一覧 | SR-00、SR-03 |
| `list_approval_flow_routes()` | 承認経路（申請経路）の一覧 | SR-00、SR-03 |
| `list_approval_requests(user)` | 紐付けできる事前申請の一覧 | SR-03 |
| `upload_receipt(user, pdf, file_name)` | 請求書ファイルをファイルボックスにアップロードし、その識別子を返す | SR-03 |
| `create_payment_request(user, params)` | 支払依頼を申請し、その識別子を返す | SR-03 |

- 上の 4 つは `FreeeOption`（`id`: freee 上の識別子、`name`: 表示名）の一覧を返す。税区分は freee 上で `code` が識別子のため、`code` を `id` に入れる
- SR-03 で追加した 3 つの詳細は [SR-03 の設計](./sr-03_freee_payment_request.md#freee-とのやり取り) を参照

サンプルデータは `sample_data/freee/` に JSON で置く。

| ファイル | 内容 |
|----------|------|
| `partners.json` | 取引先 |
| `account_items.json` | 勘定科目 |
| `taxes.json` | 税区分 |
| `approval_flow_routes.json` | 承認経路 |
| `approval_requests.json` | 事前申請（各種申請）。形式は [SR-03 の設計](./sr-03_freee_payment_request.md#freee-とのやり取り) を参照 |

`approval_requests.json` 以外の形式は、いずれも `[{"id": 101, "name": "株式会社Aメディア"}, ...]` とする。

## Gmail 連携

freee と違い、Gmail は最終的に実際に接続する。Gmail とのやり取りは `GmailClient` クラス 1 つに閉じ込め、中身を次の 2 段階で作る。

| 段階 | `GmailClient` の中身 |
|------|----------------------|
| 第 1 段階 | `sample_data/gmail/` の `.eml` ファイルをメールとして返す。取込処理の全体を、Gmail に接続せずに作って確かめる |
| 第 2 段階 | Gmail API で実際の Gmail に接続する形に置き換える。読み取り専用のスコープ（`gmail.readonly`）だけを使う |

- 実装の切替の仕組み（インターフェースや設定値）は設けない。第 2 段階では `GmailClient` の中身を置き換え、メソッドの形は変えない。取込処理は変えない
- 第 2 段階のあとの自動テストでは、`GmailClient` をテスト用の偽物に差し替える

メソッドと、受信用の Gmail アカウントの認証は [SR-01 の設計](./sr-01_gmail_invoice_ingest.md) を参照。

## ファイル保存

ファイルの保存は `FileStorage` インターフェースに閉じ込める。実装は 2 つ用意し、`STORAGE_BACKEND` で切り替える。

| 実装 | `STORAGE_BACKEND` | 保存先 |
|------|-------------------|--------|
| `LocalFileStorage` | `local` | `LOCAL_STORAGE_DIR` のフォルダ |
| `GcsFileStorage` | `gcs` | `GCS_BUCKET` の Cloud Storage バケット |

| メソッド | 内容 |
|----------|------|
| `save(key, data)` | `key`（保存先のパス）にファイルを保存する。同じ `key` があれば上書きする |
| `load(key)` | `key` のファイルを読み出す |

ファイルを削除するメソッドは設けない（請求書データの保持の要件のため）。

## 認証

### 暫定措置

システム要件では「利用者は freee のユーザーであり、freee のアカウントでログインする」を前提としている。ただし、本リポジトリでは freee のアカウントを発行せずに進める。そのため、Google Cloud 上でも freee のアカウントではログインせず、Google アカウントでの簡易ログインで代替する。freee のアカウントを発行して実接続に切り替えるときに、ログイン方式を見直す。

### 方式

| 環境 | `AUTH_MODE` | 方式 |
|------|-------------|------|
| Google Cloud | `iap` | Cloud Run の前段の IAP（Identity-Aware Proxy）で、Google アカウントでのログインを求める |
| ローカル | `dev` | ログインを省略し、固定の開発ユーザー（メールアドレス `dev@example.com`）として扱う |

Google Cloud（`AUTH_MODE=iap`）の動き:

- ログインとアクセスの許可は IAP が行う。アプリにはログイン画面やセッション管理を実装しない
- アクセスを許可する Google アカウントは、メールアドレスを 1 件ずつ IAM で許可する（IAP で保護されたウェブアプリ ユーザーのロール）。ドメイン単位の許可はしない
- アプリは、IAP が付けるリクエストヘッダー `X-Goog-IAP-JWT-Assertion` の署名を検証し、そこから利用者のメールアドレスを取り出す。検証に失敗したリクエストは拒否する
- 利用者のメールアドレスは、SR-03 で申請者として記録する（[SR-03 の設計](./sr-03_freee_payment_request.md#申請)）

SR-00 は、利用者が誰であるかを記録しない。ログインしていることだけを求める。

## ディレクトリ構成

```text
.
├── app/
│   ├── main.py               # FastAPI アプリの生成、ルーティングの登録
│   ├── config.py             # 環境変数の読み込み
│   ├── db.py                 # DB 接続・セッション
│   ├── auth.py               # 認証（dev / iap の切替）
│   ├── csrf.py               # CSRF 対策（Origin ヘッダーの確認）
│   ├── errors.py             # エラーの画面（404・403・500）
│   ├── freee/
│   │   ├── client.py         # FreeeClient インターフェース、FreeeOption
│   │   └── sample_client.py  # SampleFreeeClient
│   ├── gmail/
│   │   ├── client.py         # GmailClient（第 1 段階はサンプル、第 2 段階で Gmail API）
│   │   └── authorize.py      # Gmail の接続許可を取得するコマンド（第 2 段階）
│   ├── storage/
│   │   ├── storage.py        # FileStorage インターフェース
│   │   ├── local.py          # LocalFileStorage
│   │   └── gcs.py            # GcsFileStorage
│   ├── partners/             # SR-00
│   │   ├── models.py         # テーブル定義
│   │   ├── repository.py     # PartnerRepository
│   │   ├── service.py        # 入力チェック・登録・変更・削除
│   │   └── routes.py         # 画面のルーティング
│   ├── invoices/             # SR-01
│   │   ├── models.py         # テーブル定義
│   │   ├── repository.py     # InvoiceRepository
│   │   └── ingest.py         # 取込処理
│   ├── extraction/           # SR-02
│   │   ├── models.py         # テーブル定義
│   │   ├── repository.py     # ExtractionRepository
│   │   ├── extractor.py      # InvoiceExtractor（第 1 段階はサンプル、第 2 段階で Gemini）
│   │   ├── validation.py     # 読み取った値の形式チェック
│   │   └── extract.py        # 抽出処理
│   ├── payment_requests/     # SR-03
│   │   ├── models.py         # テーブル定義
│   │   ├── repository.py     # 一覧の検索、支払い依頼インプットの読み書き
│   │   ├── service.py        # インプットの作成・保存・入力チェック・申請
│   │   └── routes.py         # 画面のルーティング
│   ├── jobs/
│   │   └── hourly.py         # 1 時間ごとのバッチ（SR-01 の取込 → SR-02 の抽出）の起動口
│   ├── static/
│   │   └── htmx.min.js       # htmx（CDN を使わずリポジトリに置く）
│   └── templates/            # Jinja2 テンプレート（共通レイアウトは base.html）
├── migrations/               # Alembic のマイグレーション
├── sample_data/
│   ├── freee/                # freee のサンプルデータ（JSON）
│   ├── gmail/                # Gmail のサンプルのメール（.eml、第 1 段階）
│   └── extraction/           # 読み取り結果のサンプル（JSON、第 1 段階）
├── tests/
├── docker-compose.yml        # PostgreSQL（開発用とテスト用の DB）
├── pyproject.toml            # 依存関係、Ruff・mypy・pytest の設定
├── uv.lock
├── .python-version           # 3.13
└── .env.example
```

## 制約

- Web アプリの Cloud Run の最小インスタンス数を 0 とする（ユーザー確認済み）。そのため、しばらく使われなかった後の最初の表示は、インスタンスの起動を待つ分だけ遅くなり、非機能要件の「一覧・詳細の表示はいずれも 3 秒以内」を超えることがある。2 回目以降の表示は対象外。検証用のため、費用を優先する

## Google Cloud の要確認事項

次の値はまだ決まっていない。本書には値を書かない。Google Cloud の設定作業を始める前に、必ず確認して決める。

| 項目 | 状態 |
|------|------|
| 使用する Google Cloud プロジェクト（プロジェクト ID） | 未決。設定作業の前に確認する |
| リージョン | 未決。設定作業の前に確認する |
| Cloud SQL のインスタンス名・マシンタイプ・PostgreSQL のバージョン | 未決。設定作業の前に確認する |
| Cloud Run のサービス名・実行に使うサービスアカウント | 未決。設定作業の前に確認する |
| Web アプリの URL（`APP_ORIGIN` に設定する値） | 未決。設定作業の前に確認する |
| コンテナイメージを置く Artifact Registry のリポジトリ | 未決。設定作業の前に確認する |
| デプロイ方法（手動の `gcloud` か、CI か） | 未決。設定作業の前に確認する |
| IAP でアクセスを許可する Google アカウントのメールアドレス | 未決。設定作業の前に確認する |
| IAP の OAuth 同意画面の設定（アプリ名、サポートのメールアドレス、公開範囲） | 未決。設定作業の前に確認する |
| 請求書を受け取る Gmail アカウント（個人の @gmail.com を使う方針） | 未決。設定作業の前に確認する |
| Gmail API 用の OAuth クライアント（種類はデスクトップ アプリ）と同意画面（「テスト中」のまま使う方針） | 未決。設定作業の前に確認する |
| 請求書ファイルを置く Cloud Storage のバケット名・ロケーション | 未決。設定作業の前に確認する |
| 1 時間ごとのバッチの Cloud Run Jobs のジョブ名・Cloud Scheduler の設定 | 未決。設定作業の前に確認する |
| Vertex AI のロケーション・使う Gemini のモデル | 未決。設定作業の前に確認する |
| Secret Manager のシークレット名（DB のパスワード、Gmail の認証情報） | 未決。設定作業の前に確認する |
| 取込のエラーの通知先（Cloud Monitoring のアラートを使うか） | 未決。設定作業の前に確認する |
