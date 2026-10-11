# 全体構成（architecture）

全 SR に共通する基盤の設計をまとめる。本書には SR-00 の実装に必要な範囲だけを書き、SR-01 以降の設計で必要になった時点で追記する。

## 方針

- 最終的には Google Cloud 上で動かすが、まずローカルですべての機能を試せる構成にする
- ローカルと Google Cloud の差は、環境変数で切り替える設定値だけにする
- freee とは通信しない。freee から取得するデータはサンプルデータで代替する（[freee 連携の実現可能性調査](./freee_feasibility.md)）

## 技術スタック

| 項目 | 採用 |
|------|------|
| 言語 | Python |
| Web フレームワーク | FastAPI |
| 画面 | Jinja2 テンプレートによるサーバーサイド描画 |
| DB | PostgreSQL |
| DB アクセス | SQLAlchemy |
| マイグレーション | Alembic |
| テスト | pytest |

## 構成

### Google Cloud

```mermaid
flowchart LR
    User[利用者のブラウザ] --> IAP[Identity-Aware Proxy<br>Google ログイン]
    IAP --> Run[Cloud Run<br>Web アプリ]
    Run --> SQL[(Cloud SQL<br>PostgreSQL)]
    Scheduler[Cloud Scheduler] --> Job[Cloud Run Jobs<br>取込・抽出バッチ]
    Job --> SQL
    Run -.-> Secret[Secret Manager]
    Job -.-> Secret
```

- Web アプリ（SR-00、SR-03 の画面）は Cloud Run のサービス 1 つとして動かす。利用者のアクセスは IAP を通す（[認証](#認証)）
- SR-01・SR-02 の定期処理は Cloud Run Jobs と Cloud Scheduler で動かす想定とする（詳細は SR-01・SR-02 の設計で決める）
- Cloud Run から Cloud SQL へは Cloud SQL Auth Proxy（Cloud Run の Cloud SQL 接続設定）で接続する
- 秘匿情報（DB のパスワード、将来の Gmail・freee の認証情報）は Secret Manager に置き、環境変数としてアプリに渡す

### ローカル

```mermaid
flowchart LR
    User[ブラウザ] --> App[uvicorn<br>Web アプリ]
    App --> PG[(Docker の PostgreSQL)]
    App --> Sample[サンプルデータ<br>sample_data/freee/]
```

- PostgreSQL は `docker compose` で起動する
- アプリは `uvicorn` で起動する
- 秘匿情報は `.env`（Git 管理外）に置く。`.env.example` に項目だけを記載する

## 設定値

環境変数で渡す。

| 環境変数 | 内容 | ローカルの例 |
|----------|------|--------------|
| `DATABASE_URL` | DB の接続先 | `postgresql+psycopg://app:app@localhost:5432/billing` |
| `FREEE_CLIENT` | freee 連携の実装の切替。本リポジトリでは `sample` のみ | `sample` |
| `AUTH_MODE` | 認証方式の切替。ローカルは `dev`、Google Cloud は `iap` | `dev` |

## freee 連携

freee とのやり取りは `FreeeClient` インターフェースに閉じ込める。本リポジトリでは、サンプルデータを返す `SampleFreeeClient` だけを実装する。

| メソッド | 返す値 | 使う SR |
|----------|--------|---------|
| `list_partners()` | freee 上の取引先の一覧 | SR-00、SR-03 |
| `list_account_items()` | 勘定科目の一覧 | SR-00、SR-03 |
| `list_taxes()` | 税区分の一覧 | SR-00、SR-03 |
| `list_approval_flow_routes()` | 承認経路（申請経路）の一覧 | SR-00、SR-03 |

いずれも `FreeeOption`（`id`: freee 上の識別子、`name`: 表示名）の一覧を返す。税区分は freee 上で `code` が識別子のため、`code` を `id` に入れる。SR-03 で必要なメソッド（事前申請の取得、支払依頼の作成など）は SR-03 の設計で追加する。

サンプルデータは `sample_data/freee/` に JSON で置く。

| ファイル | 内容 |
|----------|------|
| `partners.json` | 取引先 |
| `account_items.json` | 勘定科目 |
| `taxes.json` | 税区分 |
| `approval_flow_routes.json` | 承認経路 |

形式はいずれも `[{"id": 101, "name": "株式会社Aメディア"}, ...]` とする。

## 認証

### 暫定措置

システム要件では「利用者は freee のユーザーであり、freee のアカウントでログインする」を前提としている。ただし、本リポジトリでは freee のアカウントを発行せずに進める。そのため、Google Cloud 上でも freee のアカウントではログインせず、Google アカウントでの簡易ログインで代替する。freee のアカウントを発行して実接続に切り替えるときに、ログイン方式を見直す。

### 方式

| 環境 | `AUTH_MODE` | 方式 |
|------|-------------|------|
| Google Cloud | `iap` | Cloud Run の前段の IAP（Identity-Aware Proxy）で、Google アカウントでのログインを求める |
| ローカル | `dev` | ログインを省略し、固定の開発ユーザーとして扱う |

Google Cloud（`AUTH_MODE=iap`）の動き:

- ログインとアクセスの許可は IAP が行う。アプリにはログイン画面やセッション管理を実装しない
- アクセスを許可する Google アカウントは、メールアドレスを 1 件ずつ IAM で許可する（IAP で保護されたウェブアプリ ユーザーのロール）。ドメイン単位の許可はしない
- アプリは、IAP が付けるリクエストヘッダー `X-Goog-IAP-JWT-Assertion` の署名を検証し、そこから利用者のメールアドレスを取り出す。検証に失敗したリクエストは拒否する
- 利用者のメールアドレスは、SR-03 で申請者を記録するときに使う（詳細は SR-03 の設計で決める）

SR-00 は、利用者が誰であるかを記録しない。ログインしていることだけを求める。

## ディレクトリ構成

```text
.
├── app/
│   ├── main.py               # FastAPI アプリの生成、ルーティングの登録
│   ├── config.py             # 環境変数の読み込み
│   ├── db.py                 # DB 接続・セッション
│   ├── auth.py               # 認証（dev / iap の切替）
│   ├── freee/
│   │   ├── client.py         # FreeeClient インターフェース、FreeeOption
│   │   └── sample_client.py  # SampleFreeeClient
│   ├── partners/             # SR-00
│   │   ├── models.py         # テーブル定義
│   │   ├── repository.py     # PartnerRepository
│   │   ├── service.py        # 入力チェック・登録・変更・削除
│   │   └── routes.py         # 画面のルーティング
│   └── templates/            # Jinja2 テンプレート
├── migrations/               # Alembic のマイグレーション
├── sample_data/
│   └── freee/                # freee のサンプルデータ（JSON）
├── tests/
├── docker-compose.yml
└── .env.example
```

## Google Cloud の要確認事項

次の値はまだ決まっていない。本書には値を書かない。Google Cloud の設定作業を始める前に、必ず確認して決める。

| 項目 | 状態 |
|------|------|
| 使用する Google Cloud プロジェクト（プロジェクト ID） | 未決。設定作業の前に確認する |
| リージョン | 未決。設定作業の前に確認する |
| Cloud SQL のインスタンス名・マシンタイプ・PostgreSQL のバージョン | 未決。設定作業の前に確認する |
| Cloud Run のサービス名・実行に使うサービスアカウント | 未決。設定作業の前に確認する |
| コンテナイメージを置く Artifact Registry のリポジトリ | 未決。設定作業の前に確認する |
| デプロイ方法（手動の `gcloud` か、CI か） | 未決。設定作業の前に確認する |
| IAP でアクセスを許可する Google アカウントのメールアドレス | 未決。設定作業の前に確認する |
| IAP の OAuth 同意画面の設定（アプリ名、サポートのメールアドレス、公開範囲） | 未決。設定作業の前に確認する |
