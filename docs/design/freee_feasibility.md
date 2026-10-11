# freee 連携の実現可能性調査

システム要件（SR-00、SR-03）が freee 会計の仕様上実現できるかを確認した結果をまとめる。

本リポジトリでは freee と実際には通信せず、サンプルデータで代替する。本調査は、実接続に切り替えたときに要件が成り立つことを担保するために行う。

調査日: 2026-10-11

## 参照資料

- [freee会計支払依頼APIの使い方](https://developer.freee.co.jp/guideline/accounting-payment-requests)
- [freee会計各種申請APIの使い方](https://developer.freee.co.jp/guideline/accounting-approval-requests)
- [freee-accounting-sdk-php: PaymentRequestCreateParams](https://github.com/freee/freee-accounting-sdk-php/blob/master/docs/Model/PaymentRequestCreateParams.md)
- [freee-accounting-sdk-php: ApprovalRequestsApi](https://github.com/freee/freee-accounting-sdk-php/blob/master/docs/Api/ApprovalRequestsApi.md)
- [freee-accounting-sdk-php: ReceiptsApi](https://github.com/freee/freee-accounting-sdk-php/blob/master/docs/Api/ReceiptsApi.md)

SDK は 2023 年 4 月に定期メンテナンスを終了しているため、実装時は公式 API リファレンスで最新仕様を再確認する。

## 前提条件

- 支払依頼・各種申請は、freee 会計の法人プロフェッショナルプランまたは法人エンタープライズプランでのみ利用できる
- freee の API は、認可した freee ユーザーの権限で動作する

## 結果一覧

| 要件 | 判定 | freee の仕様 |
|------|------|--------------|
| 事前申請の取得（SR-03-1） | 実現可（条件あり） | 事前申請は freee の「各種申請」に当たる。`GET /api/1/approval_requests` で一覧を取得できる |
| 利用者のメールアドレスに共有されている事前申請に絞る（SR-03-1） | 実現不可 | 各種申請に「メールアドレスへの共有」という概念がない。絞り込みに使えるのは申請者、承認者（申請中のみ）、申請ステータス、申請タイトル、申請フォーム、申請日、金額 |
| 件名での検索（SR-03-1） | 実現可 | 一覧取得の `title`（申請タイトル）で絞り込める |
| 事前申請との紐付け（SR-03-3） | 実現可（条件あり） | 支払依頼作成時の `parent_id` に各種申請 ID を指定する。下記「紐付けの制約」を参照 |
| 1 つの事前申請を複数の請求書に紐付ける（SR-03-1） | 実現可（上限あり） | 1 つの各種申請から作成できる経費精算・支払依頼・各種申請は合計 15 件まで |
| 支払依頼の申請（SR-03-3） | 実現可 | `POST /api/1/payment_requests` で `draft: false` を指定すると申請中で作成される |
| 申請者を操作した利用者にする（SR-03-3） | 実現可（条件あり） | 支払依頼の申請者は API を認可したユーザーになる。利用者ごとに freee ユーザーとして認可する必要がある |
| 請求書ファイルの添付（SR-03-3） | 実現可 | `POST /api/1/receipts` でファイルボックスにアップロードし、得た ID を支払依頼の `receipt_ids` に指定する |
| freee 上の取引先・勘定科目・税区分・承認経路の選択（SR-00、SR-03-2） | 実現可 | それぞれ freee の取引先・勘定科目・税区分・申請経路の一覧から取得した ID を指定する |
| 申請成功時の識別子の記録（SR-03-3） | 実現可 | 作成した支払依頼の ID が応答で返る |

## 紐付けの制約

`parent_id` に指定できる各種申請は、次の条件をすべて満たすものに限られる。

- 申請ステータスが承認済み（approved）である
- その各種申請から取引を作成していない
- その各種申請から振替伝票を作成していない
- その各種申請から作成した経費精算・支払依頼・各種申請が合計 15 件未満である

## 支払い依頼インプットと freee 項目の対応

| 支払い依頼インプットの項目 | freee 支払依頼の項目 | 備考 |
|----------------------------|----------------------|------|
| freee 上の取引先 | `partner_id` | |
| 請求書番号 | `document_code` | 255 文字以内 |
| 請求書発行日 | `issue_date`（発生日） | 必須 |
| 支払期日 | `payment_date`（支払期限） | |
| 税込金額 | `payment_request_lines.amount` | 申請中で作成する場合は 1 以上 |
| 勘定科目 | `payment_request_lines.account_item_id` | |
| 税区分 | `payment_request_lines.tax_code` | 勘定科目を指定する場合は必須 |
| 承認経路 | `approval_flow_route_id` | 必須 |
| 紐付けた事前申請 | `parent_id` | 上記の制約あり |
| 請求書ファイル | `receipt_ids` | 事前にファイルボックスへアップロード |
| 適格請求書発行事業者登録番号 | なし | 支払依頼に対応する項目がない。ファイルボックスのアップロード時に適格請求書かどうか（`qualified_invoice`）は指定できる |
| 税抜金額、消費税額 | なし | 支払依頼の明細は金額と税区分で表現する |
| 申請タイトル | `title` | 必須。初期値は `{申請月}_{媒体名}_メディア費`（SR-03） |

## 要件への影響

| 内容 | 対応 |
|------|------|
| 「利用者のメールアドレスに共有されている事前申請」は実現できない | SR-03-1 を「利用者が freee 上で閲覧できる事前申請」に変更した（反映済み） |
| 紐付けできるのは承認済みで、上記の制約を満たす各種申請だけ | SR-03-1 の取得条件に、紐付けの制約をすべて追加した（反映済み） |
| 申請者を利用者本人にするには、利用者ごとの freee 認可が必要 | 「利用者は freee のユーザーで、freee のアカウントでログインする」を前提に追加した（反映済み） |
| freee 側の申請フォームで「入力の必須化」をした項目は、API でも必須になる | 実接続時に freee 側の設定を確認する（未対応。本リポジトリはサンプルデータのため対象外） |
| 申請タイトルが要件で決まっていない | SR-03 で初期値を `{申請月}_{媒体名}_メディア費` と定めた（反映済み） |
| 適格請求書発行事業者登録番号は支払依頼に送れない | 本システム内でのみ保持する。freee には送らない前提で設計する（未対応） |
