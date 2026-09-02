# ORION assistant workflow

For every assistant response about ORION, the first visible line must be one of:

- `ORION ARCHITECTURE GUARD: ON`
- `ORION ARCHITECTURE GUARD: REQUIRED`
- `ORION ARCHITECTURE GUARD: OFF`

Use `ON` only when the response or task is grounded in an applicable, actual
Architecture Guard result. For architecture-changing work, include the concrete
AG-3 report ID: `ORION ARCHITECTURE GUARD: ON — AG-...`.

Use `REQUIRED` when discussion has reached an architecture decision or change.
Run the Guard before recommending, approving, or implementing that architecture.

Use `OFF` when the Guard was not applied. It is allowed for non-architectural
ORION explanation, status, or chitchat, but do not recommend, approve, or assert
a new ORION architecture decision while `OFF`.

The status line is mandatory. Do not place any text or Markdown before it.
Omission is a process violation. This is durable decision D73 and is effective
immediately.
