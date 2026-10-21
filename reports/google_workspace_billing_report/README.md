# Google Workspace Entitlements Report

This report lists Google Workspace subscriptions together with the matching
entitlement data read from the Google Partner Sales Console, so that
distributors can reconcile what Connect holds against what Google holds.

For every subscription it reports:

- the Connect subscription, customer, tier, contract, marketplace and hub data
- the Google entitlement id, status and suspension reasons
- the Google offer id, SKU, product and display name
- the Google offer base and effective price
- assigned, maximum and purchased unit counts, and the latest reported consumption
- the Google creation time and the commitment start and end dates

You can configure the report according to the following:

- Subscription creation date range
- Transaction type (test, production)
- List of marketplaces
- List of products (Google products only)

Subscriptions in `active`, `suspended`, `terminating` and `terminated` status
are included.

If the Google data cannot be read for a subscription, the row is still
reported and the reason is given in the last column, `Error Details`.
