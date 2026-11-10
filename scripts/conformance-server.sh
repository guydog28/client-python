#!/usr/bin/env bash
# Runs server-slice conformance plans against a live rest-api instance.
#
# Reads the vendored plans (vendor/spec/plans/v1/) tagged slice=server, sends
# each case to the provided URL, and subset-matches responses against expected
# shapes.
#
# Usage: bash scripts/conformance-server.sh <url>
#   or:  EZC_SMOKE_URL=http://host:3000 bash scripts/conformance-server.sh
set -euo pipefail

URL="${1:-${EZC_SMOKE_URL:-}}"
if [[ -z "$URL" ]]; then
  printf 'usage: %s <url>\n  or set EZC_SMOKE_URL\n' "$0" >&2
  exit 1
fi

python3 - "$URL" <<'PY'
import sys
import os
import json
import urllib.request
import urllib.error
import urllib.parse
import pathlib

url = sys.argv[1].rstrip('/')
plans_dir = pathlib.Path('vendor/spec/plans/v1')

def subset_match(actual, expected):
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        # bool is an int subclass; True must not satisfy an expected 1.
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and actual == expected
        )
    if isinstance(expected, str):
        return actual == expected
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) < len(expected):
            return False
        return all(subset_match(actual[i], expected[i]) for i in range(len(expected)))
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(subset_match(actual.get(k), v) for k, v in expected.items())
    return actual == expected

CTX_PATHS = {
    'ctxProcess':        lambda ci, cv: f'/v1/ctx/{ci}/{cv}/scheme/process',
    'ctxValidate':       lambda ci, cv: f'/v1/ctx/{ci}/{cv}/scheme/validate',
    'ctxAggregate':      lambda ci, cv: f'/v1/ctx/{ci}/{cv}/scheme/aggregate',
    'ctxScan':           lambda ci, cv: f'/v1/ctx/{ci}/{cv}/scheme/scan',
    'ctxDocumentAudit':  lambda ci, cv: f'/v1/ctx/{ci}/{cv}/document/audit',
}

CTX_BODIES = {
    'ctxProcess':        lambda args: {'input': args[0] if args else ''},
    'ctxValidate':       lambda args: {'input': args[0] if args else ''},
    'ctxAggregate':      lambda args: {'inputs': args[0] if args else []},
    'ctxScan':           lambda args: {'text':  args[0] if args else ''},
    'ctxDocumentAudit':  lambda args: {'text':  args[0] if args else ''},
}


def case_path(path, tc):
    """Add the case's scheme selector, when it names one, as the declared ?scheme= query."""
    scheme = tc.get('scheme')
    if scheme is None:
        return path
    return f"{path}?{urllib.parse.urlencode({'scheme': scheme})}"


def refusal_failure(refused_with, status):
    """Judge a case that exists to be refused: None when it was, else the reason it failed."""
    if status is None:
        return f'expected HTTP {refused_with}, got a result'
    if status != refused_with:
        return f'expected HTTP {refused_with}, got HTTP {status}'
    return None

def request_headers():
    """Carry operator credentials without changing the closed request payload."""
    headers = {'Content-Type': 'application/json'}
    bearer = os.environ.get('EZC_SMOKE_ACCESS_TOKEN')
    context = os.environ.get('EZC_SMOKE_CONTEXT_TOKEN')
    if bearer:
        headers['Authorization'] = f'Bearer {bearer}'
    if context:
        headers['x-ezclassify-context-token'] = context
    return headers


def response_value(envelope, method):
    """Read the canonical Context envelope and project scan summaries for plans."""
    if not isinstance(envelope, dict) or 'result' not in envelope:
        raise ValueError('Context response is missing its result envelope')
    actual = envelope['result']
    if method != 'ctxScan':
        return actual
    if not isinstance(actual, dict) or not isinstance(actual.get('results'), list):
        raise ValueError('Context scan result must carry its results array')
    actual = actual['results']
    first = actual[0] if actual else {}
    return {
        'count': len(actual),
        'firstMarking': first.get('marking'),
        'firstStart': first.get('start'),
        'firstRendered': (first.get('result') or {}).get('rendered'),
    }


passed = 0
failed = 0
unsupported_methods: set[str] = set()

for plan_file in sorted(plans_dir.glob('*.json')):
    if plan_file.stem == 'plan-schema':
        continue
    plan = json.loads(plan_file.read_text())
    if plan.get('slice') != 'server':
        continue
    for tc in plan.get('cases', []):
        method   = tc.get('method', '')
        ctx_id   = tc.get('ctxId', '')
        ctx_ver  = tc.get('ctxVersion', '')
        args     = tc.get('args', [])
        expect   = tc.get('expect', {})
        refused_with = tc.get('refusedWith')
        name     = tc.get('name', f'{plan_file.stem}/{method}')
        path_fn  = CTX_PATHS.get(method)
        body_fn  = CTX_BODIES.get(method)
        if path_fn is None:
            print(f'  FAIL  {name}: unsupported method {method}')
            failed += 1
            unsupported_methods.add(method)
            continue
        api_path = case_path(path_fn(ctx_id, ctx_ver), tc)
        body_bytes = json.dumps(body_fn(args)).encode()
        req = urllib.request.Request(
            url + api_path,
            data=body_bytes,
            headers=request_headers(),
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                envelope = json.load(resp)
            if refused_with is not None:
                print(f'  FAIL  {name}: {refusal_failure(refused_with, None)}')
                failed += 1
                continue
            actual = response_value(envelope, method)
            if subset_match(actual, expect):
                print(f'  pass  {name}')
                passed += 1
            else:
                expect_str = json.dumps(expect, separators=(',', ':'))
                actual_str = json.dumps(actual, separators=(',', ':'))
                print(f'  FAIL  {name}')
                print(f'    expect: {expect_str}')
                print(f'    actual: {actual_str}')
                failed += 1
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors='replace')[:200]
            if refused_with is not None:
                reason = refusal_failure(refused_with, exc.code)
                if reason is None:
                    print(f'  pass  {name}')
                    passed += 1
                else:
                    print(f'  FAIL  {name}: {reason} {body_text}')
                    failed += 1
                continue
            print(f'  FAIL  {name}: HTTP {exc.code} {body_text}')
            failed += 1
        except Exception as exc:
            print(f'  FAIL  {name}: {exc}')
            failed += 1

total_run = passed + failed
print(f'\n{passed}/{total_run} server-slice cases passed')
if unsupported_methods:
    # Name unsupported dispatch alongside its failing case count.
    print(f'  methods this runner does not send: {", ".join(sorted(unsupported_methods))}')
if total_run == 0:
    print(f'error: no server-slice cases found under {plans_dir}', file=sys.stderr)
    sys.exit(1)
if failed > 0:
    sys.exit(1)
PY
