# SR-01 Gmail からの請求書取込・蓄積 設計

対応システム要件: [SR-01 Gmail からの請求書取込・蓄積](../requirements/system_requirements/sr-01_gmail_invoice_ingest.md)

共通の構成は [全体構成](./architecture.md) を参照。

## 要件との対応

| 要件 | 設計での対応 |
|------|--------------|
| 1. 1 時間ごとに自動で取込を実行する | Cloud Scheduler から Cloud Run Jobs を 1 時間ごとに起動する（[実行](#実行)） |
| 2. 取込対象のメールの条件 | [取込対象の判定](#取込対象の判定) |
| 3. PDF 添付ファイル 1 件ごとに請求書データを 1 件作成する | [取込の流れ](#取込の流れ) の 5〜7 |
| 4. 内容が完全に同じ PDF は請求書データを作らない | PDF の SHA-256 で判定する（[重複の判定](#重複の判定)） |
| 5. 失敗したメールは次回再度取り込む | 成功したメールだけを取込済みとして記録する（[エラー時の動き](#エラー時の動き)） |
| 6. Gmail 上のメールを変更・削除しない | Gmail API は読み取り専用のスコープだけを使う（[Gmail への接続](#gmail-への接続)） |
| 非機能: 取込遅延 2 時間以内 | 1 時間ごとの実行で満たす。ただし [制約](#制約) の場合を除く |
| 非機能: Gmail は読み取りのみ | スコープ `gmail.readonly` だけを許可する |
| 非機能: Gmail の認証情報を平文で残さない | Secret Manager と Git 管理外のファイルに置く（[Gmail への接続](#gmail-への接続)） |
| 非機能: 請求書データを削除しない | 削除する処理を作らない。`FileStorage` にも削除のメソッドを設けない |

## データモデル

### `invoices`（請求書データ）

| 列 | 型 | 制約 | 内容 |
|----|----|------|------|
| `id` | UUID | 主キー | 請求書 ID |
| `file_key` | text | NOT NULL | `FileStorage` 上の保存先（`invoices/{file_sha256}.pdf`） |
| `file_sha256` | text | NOT NULL、一意 | PDF の中身の SHA-256（16 進数の文字列） |
| `file_name` | text | NOT NULL | 添付時のファイル名 |
| `sender_email` | text | NOT NULL | 送信元メールアドレス（小文字に正規化済み） |
| `subject` | text | NOT NULL | メールの件名（件名がない場合は空文字） |
| `received_at` | timestamptz | NOT NULL | Gmail の受信日時 |
| `ingested_at` | timestamptz | NOT NULL | 取込日時 |
| `gmail_message_id` | text | NOT NULL | 取込元のメールの Gmail 上の ID（調査用） |

- 一意インデックス `uq_invoices_file_sha256`: `UNIQUE (file_sha256)`
- 要件の Output のうち「請求書ファイル」は、`file_key` で `FileStorage` から読み出す
- `sender_email` を正規化して持つことで、SR-02 で取引先を照合するとき（SR-00 の `find_active_by_email`）に大文字小文字の違いを気にしなくてよい

### `ingested_messages`（取込済みのメール）

| 列 | 型 | 制約 | 内容 |
|----|----|------|------|
| `gmail_message_id` | text | 主キー | 取り込んだメールの Gmail 上の ID |
| `ingested_at` | timestamptz | NOT NULL | 取込日時 |

- 要件 2 の「まだ取り込んでいない」は、このテーブルに Gmail 上の ID がないことで判定する
- 取込に成功したメールだけを記録する。PDF がすべて重複していて請求書データを 1 件も作らなかったメールも、取込に成功したものとして記録する

## Gmail への接続

### `GmailClient`

[全体構成](./architecture.md#gmail-連携) の通り、`GmailClient` クラス 1 つで、第 1 段階はサンプル、第 2 段階で Gmail API に中身を置き換える。メソッドの形は 2 つの段階で変えない。

| メソッド | 内容 |
|----------|------|
| `list_message_ids(received_after, senders)` | 取込対象の候補のメールの ID の一覧を返す |
| `get_message(message_id)` | メールを `GmailMessage` として返す |

`GmailMessage` の項目:

| 項目 | 内容 |
|------|------|
| `message_id` | Gmail 上のメールの ID |
| `from_header` | From ヘッダーの値（例: `請求担当 <Billing@A-Media.jp>`） |
| `subject` | 件名 |
| `received_at` | 受信日時 |
| `attachments` | 添付ファイルの一覧。各要素は `file_name`、`mime_type`、`data`（中身のバイト列） |

`list_message_ids` は候補を絞るためのもので、取込対象かどうかの最終的な判定は取込処理が行う（[取込対象の判定](#取込対象の判定)）。そのため、2 つの段階で候補の絞り方が違っても、取込の結果は変わらない。

| 段階 | `list_message_ids` | `get_message` |
|------|--------------------|---------------|
| 第 1 段階 | `sample_data/gmail/` の `.eml` ファイルをすべて返す。ファイル名（拡張子を除く）をメールの ID とする | `.eml` ファイルを読む。受信日時は Date ヘッダーの値とする |
| 第 2 段階 | Gmail API の `users.messages.list` を、検索条件 `after:{received_after の UNIX 時刻} has:attachment from:({senders を OR でつないだもの})` で呼ぶ。ページングで全件を取る | `users.messages.get`（`format=full`）でメールを取り、添付ファイルの中身は `users.messages.attachments.get` で取る。受信日時は `internalDate` とする |

第 2 段階の補足:

- 迷惑メールとゴミ箱のメールは取り込まない。`users.messages.list` の `includeSpamTrash` を指定しない（既定で除外される）
- 添付ファイルは、メールの MIME パートを入れ子までたどり、ファイル名があるパートをすべて集める

### Gmail の認証（第 2 段階）

| 項目 | 内容 |
|------|------|
| 受信用のアカウント | 個人の @gmail.com アカウント（アカウントは要確認。[全体構成](./architecture.md#google-cloud-の要確認事項)） |
| 方式 | OAuth 2.0。OAuth クライアントの種類はデスクトップ アプリとする |
| スコープ | `https://www.googleapis.com/auth/gmail.readonly` だけ |
| 認証情報 | OAuth クライアントの ID・シークレットと、リフレッシュトークンを 1 つの JSON にまとめる |
| 認証情報の置き場所 | ローカル: `.local/gmail_token.json`（Git 管理外）。Google Cloud: Secret Manager に置き、Cloud Run Jobs にファイルとしてマウントする。どちらも `GMAIL_TOKEN_FILE` で場所を渡す |
| 接続許可の取得 | `python -m app.gmail.authorize` を実行すると、ブラウザで Google の許可画面が開く。許可すると認証情報の JSON を `.local/gmail_token.json` に書き出す。Google Cloud で使う場合は、その JSON を Secret Manager の新しいバージョンとして登録する |

OAuth 同意画面は「テスト中」のまま使うため、リフレッシュトークンは 7 日で失効する。失効したら、上の「接続許可の取得」をやり直す。

## 取込対象の判定

要件 2 の条件を、取込処理で次のように判定する。すべて満たすメールを取り込む。

| 要件の条件 | 判定方法 |
|------------|----------|
| 受信日時が運用開始日以降 | `received_at` が `INGEST_START_DATE` の日本時間 0 時以降 |
| 受信日時が取込を実行する日の 60 日前の日以降 | `received_at` が、取込を実行する日（日本時間）の 60 日前の日の日本時間 0 時以降。例: 12/10 に実行する場合は 10/11 0:00 以降 |
| 送信元が SR-00 で登録されている | From ヘッダーからメールアドレスを取り出し（Python の `email.utils.parseaddr`）、前後の空白を除いて小文字にしたものが、SR-00 の `list_active_emails()` に含まれる |
| PDF ファイルが 1 件以上添付されている | 添付ファイルのうち、`mime_type` が `application/pdf`、またはファイル名が `.pdf` で終わる（大文字小文字を区別しない）ものが 1 件以上ある |
| まだ取り込んでいない | `ingested_messages` に Gmail 上の ID がない |

- 受信日時の 2 つの条件は、遅い方の日時（以下「取込の起点」）以降であることとしてまとめて判定する
- 上の条件を満たさないメールは、`ingested_messages` に記録しない。そのため、後から SR-00 で送信元メールアドレスを登録すると、取込の起点以降の過去のメールも次回の取込で取り込まれる
- 迷惑メールとゴミ箱のメールは取り込まない（ユーザー確認済み）。迷惑メールに入った請求書は、利用者が Gmail で「迷惑メールではない」に戻すと、次回の取込で取り込まれる

## 取込の流れ

1 時間ごとのバッチ（`app/jobs/hourly.py`）が、DB の advisory lock を取ったうえで `app/invoices/ingest.py` の取込処理を呼ぶ。バッチの全体（取込のあとに SR-02 の抽出を行うこと、ロック）は [SR-02 の設計](./sr-02_invoice_field_extraction.md#1-時間ごとのバッチ) を参照。

1. SR-00 の `list_active_emails()` で、有効な取引先の送信元メールアドレスを取る。1 件もなければ終わる
2. `GmailClient.list_message_ids(取込の起点, 送信元メールアドレスの一覧)` で候補のメールの ID を取る
3. 候補のうち `ingested_messages` にないものについて、1 通ずつ次の 4〜7 を行う
4. `GmailClient.get_message` でメールを取り、[取込対象の判定](#取込対象の判定) をする。対象でなければ次のメールへ
5. PDF の添付ファイルごとに SHA-256 を計算する。同じメールの中で同じ中身のものは 1 件にまとめる。`invoices` に同じ `file_sha256` があるものは除く
6. 残った PDF を `FileStorage.save("invoices/{file_sha256}.pdf", data)` で保存する
7. 1 トランザクションで、残った PDF ごとに `invoices` に 1 行を追加し、`ingested_messages` にメールを記録する

- 6 の保存先は中身の SHA-256 で決まる。そのため、6 のあと 7 の前に失敗して次回やり直しても、同じ場所に同じ中身を上書きするだけで、ファイルが重複しない

## 重複の判定

- 要件 4 の「内容が完全に同じ PDF ファイル」は、PDF の中身のバイト列の SHA-256 が一致することで判定する
- ファイル名・送信元・メールが違っても、中身が同じなら重複として扱う
- 取込の流れの 5 で判定し、`uq_invoices_file_sha256` でも防ぐ

## エラー時の動き

| エラー | 動き |
|--------|------|
| 1 通のメールの処理中のエラー（添付ファイルの取得失敗、保存失敗、DB エラーなど） | そのメールのトランザクションを取り消し、エラーをログに出して次のメールへ進む。`ingested_messages` に記録しないので、次回の取込で再度取り込む（要件 5） |
| Gmail の認証のエラー（リフレッシュトークンの失効など） | 取込全体を止め、「Gmail の接続許可が切れています。接続許可を取り直してください」とエラーをログに出す。続く SR-02 の抽出は行い、ジョブは最後に失敗として終わる |
| Gmail API の一時的なエラー（レート制限、5xx） | Google のクライアントライブラリの再試行に任せる。それでも失敗した場合は、上の 1 通のメールの処理中のエラーと同じに扱う（一覧の取得で失敗した場合は取込全体を止める） |

- ログは標準出力に出す。Google Cloud 上では Cloud Logging に集まる
- エラーの通知先（Cloud Monitoring のアラートを使うか）は要確認とする

## 実行

| 環境 | 起動方法 |
|------|----------|
| Google Cloud | Cloud Scheduler が 1 時間ごとに Cloud Run Jobs のジョブを起動する。ジョブは `python -m app.jobs.hourly` を実行する |
| ローカル | `python -m app.jobs.hourly` を手動で実行する |

## 制約

- 第 2 段階では、OAuth 同意画面を「テスト中」のまま使う（ユーザー確認済み）。そのため、リフレッシュトークンが 7 日で失効し、接続許可を取り直すまでの間は取込が止まる。この間は、非機能要件の「メール受信から請求書データの作成まで 2 時間以内」を満たせない
- 接続許可を取り直せば、止まっていた間に届いたメールも、次回の取込でまとめて取り込まれる（取込済みとして記録されていないため）。ただし、取込を実行する日の 60 日前の日より前に届いたメールは取り込まれない
- 取込を実行する日の 60 日前の日より前に届いたメールは、取り込まれないまま対象から外れる。たとえば、エラーで 60 日以上取り込めなかったメールや、受信から 60 日以上たってから SR-00 に送信元メールアドレスを登録したメールは、取り込まれない

## ローカルでの試し方

### 第 1 段階（サンプルのメール）

1. [SR-00 のローカルでの試し方](./sr-00_partner_management.md#ローカルでの試し方) の 1〜3 を行う
2. SR-00 の画面で、サンプルのメールの送信元メールアドレス（`billing@a-media.jp`、`invoice@b-networks.jp`、`info@c-ad.jp`、`billing@d-publishing.jp`）を持つ取引先を登録する。`unknown@example.com` は登録しない
3. `python -m app.jobs.hourly` を実行する
4. `invoices` の行と `.local/storage/invoices/` のファイルができていることを確認する

サンプルのメールは `sample_data/gmail/` に置く。`scripts/generate_gmail_samples.py` で作り直せる。添付する PDF は毎回同じ中身になるように作る（SR-02 のサンプルの読み取り結果を PDF の SHA-256 で探すため）。次の場合を確かめられるように用意する。

| サンプル | 確かめること |
|----------|--------------|
| 登録済みの送信元から、PDF 1 件 | 請求書データが 1 件できる |
| 登録済みの送信元から、PDF 2 件 | 請求書データが 2 件できる |
| 登録済みの送信元から、種類が `application/octet-stream` でファイル名が `.PDF` の添付 | PDF として取り込まれる |
| 登録済みの送信元から、PDF 以外の添付だけ | 取り込まれない |
| 登録されていない送信元から、PDF 1 件 | 取り込まれない |
| 送信元のアドレスに大文字を含む | 取り込まれる |
| 運用開始日より前の受信 | 取り込まれない |
| 他のメールと同じ中身の PDF | 請求書データができない |

### 第 2 段階（実際の Gmail）

1. Gmail API 用の OAuth クライアントを作り（Google Cloud の設定のため、作業前に確認する）、`python -m app.gmail.authorize` で `.local/gmail_token.json` を作る
2. 受信用の Gmail アカウントに、登録済みの送信元から PDF 付きのメールを送る
3. `python -m app.jobs.hourly` を実行する

## テスト観点

| 観点 | 内容 |
|------|------|
| 取込対象の判定 | 要件 2 の条件を 1 つずつ外したメールが取り込まれないこと。すべて満たすメールが取り込まれること |
| PDF の判定 | `application/pdf`、拡張子 `.pdf`・`.PDF` のどちらでも PDF として扱われること。それ以外は扱われないこと |
| 送信元の照合 | From ヘッダーの表示名付き・大文字を含むアドレスでも照合できること。SR-00 で削除した取引先のアドレスは取り込まれないこと |
| 請求書データの作成 | PDF 1 件ごとに 1 件作られ、Output の項目がすべて入ること |
| 重複 | 同じ中身の PDF が、同じメール内・別のメールのどちらでも 1 件しか作られないこと |
| 再取込 | 取込済みのメールが再度取り込まれないこと。処理中にエラーになったメールが次回取り込まれること |
| 同時実行 | バッチが advisory lock を取れないときに何もせず終わること |
| 認証エラー | Gmail の認証エラーで取込全体が止まり、エラーがログに出ること |

自動テストでは、`GmailClient` を、テストごとにメールを返すテスト用の偽物に差し替える。
