# OptiMCP daemon quickstart

Always-on verification: register named rulesets, run a local daemon with a bearer
token, wrap your agent so every structured emission is checked.

## 1. Install

```bash
pip install "optimcp[daemon]"
```

## 2. Set a daemon token (required)

Unauthenticated `PUT /v1/rulesets/{id}` would let anyone silently disable your
compliance checks. OptiMCP refuses to start without a token unless you bind
**loopback** and pass an explicit opt-out.

```bash
# Windows PowerShell
setx OPTIMCP_DAEMON_TOKEN "replace-with-a-long-random-secret"
# then open a new shell

# Linux / macOS
export OPTIMCP_DAEMON_TOKEN="$(openssl rand -hex 32)"
```

Non-loopback binds (`0.0.0.0`, LAN IPs, containers exposing the port) **always**
require a token; `--allow-unauthenticated-localhost` is ignored there.

## 3. Register a ruleset

```bash
optimcp-daemon register examples/register_invoice_ruleset.yaml
optimcp-daemon list
```

Rulesets live under `~/.optimcp/rulesets/` (override with `OPTIMCP_HOME`).

## 4. Run the daemon

```bash
optimcp-daemon serve --host 127.0.0.1 --port 8787
```

Loopback-only unauthenticated mode (dev only):

```bash
# unset OPTIMCP_DAEMON_TOKEN first
optimcp-daemon serve --allow-unauthenticated-localhost
```

## 5. Check a document

```bash
curl -s http://127.0.0.1:8787/v1/check \
  -H "Authorization: Bearer $OPTIMCP_DAEMON_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"ruleset_id\":\"invoices\",\"document\":{\"subtotal\":320,\"tax_rate\":0.08,\"tax\":25.6,\"total\":345.6,\"line_items\":[{\"amount\":100},{\"amount\":120},{\"amount\":110}]}}"
```

Policy `refuse` → HTTP **422** when inconsistent. Policy `observe` → 200 with
`consistent: false` and a logged violation.

## 6. Dashboard

```bash
curl -s http://127.0.0.1:8787/dashboard \
  -H "Authorization: Bearer $OPTIMCP_DAEMON_TOKEN" -o dashboard.html
```

Or open `/dashboard` in a browser and paste the token when prompted (stored in
`sessionStorage` for that tab). Query-string tokens are not accepted.

## 7. Wire an agent

See `examples/middleware_openai.py` and `examples/always_on_loop.py`.
Set `OPTIMCP_DAEMON_URL` (default `http://127.0.0.1:8787`) and
`OPTIMCP_DAEMON_TOKEN` in the agent process so middleware can authenticate.
