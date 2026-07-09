# Sendcloud API v3 — OpenAPI specifications

Reference copy of the Sendcloud **v3** API, archived as OpenAPI **3.1.0** documents.

Sendcloud does not publish a single bundled spec for v3: the API is split into one OpenAPI
document per functional domain. Each domain lives in its own sub-folder as `openapi.yaml`,
mirroring the source layout.

- **Retrieved on:** 2026-07-09
- **Source root:** `https://sendcloud.dev/.openapi/v3/<domain>/openapi.yaml`
- **Production server:** `https://panel.sendcloud.sc/api/v3`
- **Format:** OpenAPI 3.1.0 (YAML), unmodified — verbatim copies of the published files.

## Modules

| Domain | Title | Version | File |
|---|---|---|---|
| analytics | Analytics | 3.0.0 | [`analytics/openapi.yaml`](analytics/openapi.yaml) |
| auth | Authentication | 2.0.0 | [`auth/openapi.yaml`](auth/openapi.yaml) |
| brands | Brands | 3.0.0 | [`brands/openapi.yaml`](brands/openapi.yaml) |
| carriers-dp | Deutsche Post Carrier API | 3.0.0 | [`carriers-dp/openapi.yaml`](carriers-dp/openapi.yaml) |
| compat | Compat API | 3.0.0 | [`compat/openapi.yaml`](compat/openapi.yaml) |
| contracts | Contracts API | 3.0.0 | [`contracts/openapi.yaml`](contracts/openapi.yaml) |
| duties-and-taxes | Duties and Taxes API [BETA] | 3.0.0 | [`duties-and-taxes/openapi.yaml`](duties-and-taxes/openapi.yaml) |
| dynamic-checkout | Dynamic Checkout [BETA] | 3.0.0 | [`dynamic-checkout/openapi.yaml`](dynamic-checkout/openapi.yaml) |
| event-subscriptions | Event Subscriptions API | 3.0.0 | [`event-subscriptions/openapi.yaml`](event-subscriptions/openapi.yaml) |
| events | Events API | 3.0.0 | [`events/openapi.yaml`](events/openapi.yaml) |
| integrations | Integrations | 3.0.0 | [`integrations/openapi.yaml`](integrations/openapi.yaml) |
| invoice-items | Invoice Items API | 3.0.0 | [`invoice-items/openapi.yaml`](invoice-items/openapi.yaml) |
| invoices | Invoices API | 3.0.0 | [`invoices/openapi.yaml`](invoices/openapi.yaml) |
| orders | Orders | 3.0.0 | [`orders/openapi.yaml`](orders/openapi.yaml) |
| organization | Organization API | 3.0.0 | [`organization/openapi.yaml`](organization/openapi.yaml) |
| parcel-documents | Parcel documents API | 3.0.0 | [`parcel-documents/openapi.yaml`](parcel-documents/openapi.yaml) |
| parcel-statuses | Parcel statuses API | 3.0.0 | [`parcel-statuses/openapi.yaml`](parcel-statuses/openapi.yaml) |
| parcel-tracking | Parcel Tracking API | 3.0.0 | [`parcel-tracking/openapi.yaml`](parcel-tracking/openapi.yaml) |
| pickups | Pickups API | 3.0.0 | [`pickups/openapi.yaml`](pickups/openapi.yaml) |
| reporting | Reporting | 3.0.0 | [`reporting/openapi.yaml`](reporting/openapi.yaml) |
| returns | Returns | 3.0.0 | [`returns/openapi.yaml`](returns/openapi.yaml) |
| sender-addresses | Sender addresses API | 3.0.0 | [`sender-addresses/openapi.yaml`](sender-addresses/openapi.yaml) |
| service-points | Service Points API | 3.0.0 | [`service-points/openapi.yaml`](service-points/openapi.yaml) |
| ship-an-order | Ship an Order | 3.0.0 | [`ship-an-order/openapi.yaml`](ship-an-order/openapi.yaml) |
| shipments | Shipments | 3.0.0 | [`shipments/openapi.yaml`](shipments/openapi.yaml) |
| shipping-options | Shipping Options API | 3.0.0 | [`shipping-options/openapi.yaml`](shipping-options/openapi.yaml) |
| support | Support API [BETA] | 3.0.0 | [`support/openapi.yaml`](support/openapi.yaml) |
| user | User API | 3.0.0 | [`user/openapi.yaml`](user/openapi.yaml) |
| webhooks | Webhooks | 3.0.0 | [`webhooks/openapi.yaml`](webhooks/openapi.yaml) |

> Note: the `auth` document is versioned `2.0.0` (Authentication) as published by Sendcloud; all
> other modules are `3.0.0`.

## Refreshing

The source URLs are stable and require no authentication. To re-download every module:

```sh
base=https://sendcloud.dev/.openapi/v3
for d in analytics auth brands carriers-dp compat contracts duties-and-taxes \
         dynamic-checkout events event-subscriptions integrations invoice-items \
         invoices orders organization parcel-documents parcel-statuses parcel-tracking \
         pickups reporting returns sender-addresses service-points ship-an-order \
         shipments shipping-options support user webhooks; do
  curl -sSL --fail --create-dirs -o "specs/sendcloud-v3/$d/openapi.yaml" \
    "$base/$d/openapi.yaml" || echo "FAIL: $d"
done
```
