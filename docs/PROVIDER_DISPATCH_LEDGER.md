# Forward-only Provider dispatch ledger

The legacy `solution_generation_intents.provider_call_count` is retained for
backward compatibility. It is an application-marked attempt count and is
written before the adapter/network boundary; it is not evidence that a remote
Provider received a request.

Acceptance accounting uses the additive tables:

- `provider_dispatch_epochs` records the forward-only checkpoint and the
  counts of historical authorized and unresolved records. It does not rewrite
  legacy history.
- `provider_dispatch_permits` is the database-enforced single opportunity for
  an acceptance execution. `UNIQUE(acceptance_execution_id,
  dispatch_ordinal)` and `dispatch_ordinal = 1` prevent a second permit after a
  process restart.
- `provider_dispatch_events` is append-only lifecycle evidence. A
  `CALL_BOUNDARY_ENTERED` event means that application execution crossed into
  the adapter/network-call boundary; it does not prove remote receipt.

Classification is conservative: no permit is `NOT_YET_ATTEMPTED`, a permit
without boundary entry is `PROVEN_NOT_DISPATCHED`, a Provider response or
Provider HTTP error is `CONFIRMED_PROVIDER_DISPATCH`, and a boundary followed
by timeout/transport/cancellation (or an incomplete boundary) is
`POSSIBLY_DISPATCHED_INDETERMINATE`. The indeterminate state consumes the one
acceptance opportunity and blocks automatic retry.

The scoped acceptance guard checks the target, beta instance, current epoch,
quota/reservation state, retry/fallback policy, and the absence of current
execution evidence. It deliberately does not require lifetime legacy
`provider_call_count` to be zero.
