# Telemetry history diagnostics

Alpha smoke diagnostics retain up to 5,000 validated telemetry envelopes in memory for post-session analysis. The history is bounded to avoid unbounded memory and ZIP growth.

The smoke bundle exports a session summary and newline-delimited telemetry samples so diagnostics remain useful after DCS exits and the live handshake becomes stale.
