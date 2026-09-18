"""Prove the deployed frontend and backend are actually wired together.

Opening the page in a browser is the real test, but three things can be checked without one, and
each has bitten this project already:

  1. The backend is reachable and healthy.
  2. The backend returns CORS headers *for the frontend's origin*. A missing
     Access-Control-Allow-Origin produced a bare "Failed to fetch" earlier, which looks
     identical to the backend being down.
  3. The frontend was BUILT pointing at that backend. NEXT_PUBLIC_* variables are inlined at
     build time, so setting one after a deploy changes nothing until the next build. The only
     way to know is to look for the URL in the shipped JavaScript.

  python scripts/check_connection.py <frontend-url> <backend-url>
"""

from __future__ import annotations

import re
import sys

import httpx


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    frontend = sys.argv[1].rstrip("/")
    backend = sys.argv[2].rstrip("/")
    failures = 0

    with httpx.Client(timeout=60, follow_redirects=True) as c:
        print("1. backend health")
        try:
            r = c.get(f"{backend}/health")
            print(f"   HTTP {r.status_code}  {r.text[:120]}")
            if r.status_code != 200:
                failures += 1
        except Exception as exc:
            print(f"   UNREACHABLE: {exc}")
            return 1

        print("\n2. CORS for the frontend origin")
        r = c.get(f"{backend}/requirements", headers={"Origin": frontend})
        allow = r.headers.get("access-control-allow-origin")
        if allow and (allow == "*" or allow.rstrip("/") == frontend):
            print(f"   Access-Control-Allow-Origin: {allow}  -> the browser will accept this")
        else:
            print(f"   MISSING or mismatched: {allow!r} for origin {frontend}")
            print("   The API will answer correctly and the browser will still refuse it.")
            failures += 1

        print("\n   preflight (OPTIONS):")
        p = c.request(
            "OPTIONS", f"{backend}/videos",
            headers={
                "Origin": frontend,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        print(f"   HTTP {p.status_code}  allow-methods={p.headers.get('access-control-allow-methods')}")
        if p.status_code not in (200, 204):
            failures += 1

        print("\n3. frontend page loads")
        f = c.get(frontend)
        print(f"   HTTP {f.status_code}  {len(f.text):,} bytes")
        if f.status_code != 200:
            failures += 1
            return 1 if failures else 0

        print("\n4. is the backend URL baked into the shipped JavaScript?")
        # Next.js inlines NEXT_PUBLIC_* at build time, so the literal should appear in a chunk.
        scripts = re.findall(r'src="([^"]+\.js)"', f.text)
        host = backend.replace("https://", "").replace("http://", "")
        found_in = None
        checked = 0
        for src in scripts[:25]:
            url = src if src.startswith("http") else f"{frontend}{src}"
            try:
                body = c.get(url).text
            except Exception:
                continue
            checked += 1
            if host in body:
                found_in = src
                break
        if found_in:
            print(f"   found {host} in {found_in}")
        else:
            print(f"   NOT FOUND in {checked} script chunk(s)")
            print("   The frontend was built without NEXT_PUBLIC_API_URL pointing at this")
            print("   backend, so it is still calling its default. Set the variable and")
            print("   REBUILD: a redeploy without a rebuild will not pick it up.")
            failures += 1

    print()
    if failures:
        print(f"{failures} check(s) FAILED - the two are not correctly connected")
        return 1
    print("PASS - frontend and backend are connected")
    print("Still worth opening the page and uploading a clip: these checks cannot see a")
    print("render bug, which is how the live tracking view shipped broken once already.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
