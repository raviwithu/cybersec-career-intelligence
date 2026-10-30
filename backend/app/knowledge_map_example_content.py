from __future__ import annotations

# Example knowledge map content submitted as proposals by knowledge_map_examples.py (KM-5). Pure data.
# Every reference is a public standards, OWASP, NIST, IETF or NVD page, marked "unverified" for the administrator
# to verify during review. No exploitation in the wild is claimed. Where no citable real-world example was
# included, real_world_examples is omitted and the reason is recorded in EXAMPLE_NOTES.

LEVEL_SLUGS = ("junior", "intermediate", "senior", "architect", "manager")


def _ref(title: str, url: str, publisher: str, source_type: str = "standard", locator: str | None = None) -> dict:
    item = {"title": title, "url": url, "publisher": publisher, "source_type": source_type, "verification_status": "unverified"}
    if locator:
        item["locator"] = locator
    return item


def _seq(title: str, variant: str, nodes: list[tuple], edges: list[tuple], kind: str = "sequence", boundaries: list[tuple] = ()) -> dict:
    return {
        "kind": kind, "title": title, "variant": variant,
        "nodes": [{"id": node[0], "label": node[1], "type": node[2], **({"boundary": node[3]} if len(node) > 3 else {})} for node in nodes],
        "edges": [{"from": source, "to": target, "label": label, "order": index} for index, (source, target, label) in enumerate(edges, start=1)],
        "boundaries": [{"id": boundary_id, "label": label} for boundary_id, label in boundaries],
    }


OWASP_API1 = _ref("OWASP API Security Top 10 2023: API1 Broken Object Level Authorization", "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/", "OWASP")
CWE_639 = _ref("CWE-639: Authorization Bypass Through User-Controlled Key", "https://cwe.mitre.org/data/definitions/639.html", "MITRE")
OWASP_AUTHZ = _ref("OWASP Authorization Cheat Sheet", "https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html", "OWASP", "technical_article")
OWASP_API7 = _ref("OWASP API Security Top 10 2023: API7 Server Side Request Forgery", "https://owasp.org/API-Security/editions/2023/en/0xa7-server-side-request-forgery/", "OWASP")
CWE_918 = _ref("CWE-918: Server-Side Request Forgery (SSRF)", "https://cwe.mitre.org/data/definitions/918.html", "MITRE")
OWASP_SSRF = _ref("OWASP Server-Side Request Forgery Prevention Cheat Sheet", "https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html", "OWASP", "technical_article")
AWS_IMDS = _ref("Configure the instance metadata service options", "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html", "Amazon Web Services", "vendor_documentation")
RFC_6749 = _ref("RFC 6749: The OAuth 2.0 Authorization Framework", "https://www.rfc-editor.org/rfc/rfc6749", "IETF")
RFC_7636 = _ref("RFC 7636: Proof Key for Code Exchange by OAuth Public Clients", "https://www.rfc-editor.org/rfc/rfc7636", "IETF")
RFC_9700 = _ref("RFC 9700: Best Current Practice for OAuth 2.0 Security", "https://www.rfc-editor.org/rfc/rfc9700", "IETF")
NIST_193 = _ref("NIST SP 800-193: Platform Firmware Resiliency Guidelines", "https://csrc.nist.gov/pubs/sp/800/193/final", "NIST")
NIST_147 = _ref("NIST SP 800-147: BIOS Protection Guidelines", "https://csrc.nist.gov/pubs/sp/800/147/final", "NIST")
UEFI_SPECS = _ref("UEFI Specifications", "https://uefi.org/specifications", "UEFI Forum")
RFC_9019 = _ref("RFC 9019: A Firmware Update Architecture for Internet of Things", "https://www.rfc-editor.org/rfc/rfc9019", "IETF")
RFC_9124 = _ref("RFC 9124: A Manifest Information Model for Firmware Updates in IoT Devices", "https://www.rfc-editor.org/rfc/rfc9124", "IETF")
NVD_BOOTHOLE = _ref("NVD: CVE-2020-10713", "https://nvd.nist.gov/vuln/detail/CVE-2020-10713", "NIST NVD", "vulnerability_database")


EXAMPLE_TOPICS: list[dict] = [
    {
        "topic_key": "idor-bola",
        "name": "IDOR / BOLA",
        "aliases": ["IDOR", "BOLA", "Insecure Direct Object Reference", "Broken Object Level Authorization"],
        "description": "Accessing another user's records by changing an object identifier the server does not check.",
        "placements": [("cloud-api-security", "vulnerabilities"), ("web-application-security", "vulnerabilities")],
        "relationships": [("api-authorization", "mitigated_by")],
        "references": [OWASP_API1, CWE_639, OWASP_AUTHZ],
        "sections": {
            "overview": {
                "short_description": "An attacker reads or changes another user's data by changing an identifier, such as an order number, in a request the server trusts.",
                "technical_explanation": "Insecure Direct Object Reference (IDOR), called Broken Object Level Authorization (BOLA) in APIs, happens when an endpoint authenticates the caller but never checks that the caller may access the specific object named in the path, query or body. Identifiers that are sequential or guessable make it easy to exploit, but random identifiers alone do not fix it.",
                "key_concepts": ["Object-level authorization", "Authentication versus authorization", "Ownership and tenancy checks", "Indirect references"],
                "related_technologies": ["REST and GraphQL APIs", "ORMs", "Multi-tenant SaaS"],
            },
            "how_it_works": {
                "workflow": "The client sends a request with an object identifier. The server confirms the session is valid, loads the object by identifier alone and returns it, without checking that the object belongs to the caller.",
                "architecture_explanation": "The fix belongs in the data access layer: every lookup is scoped by the caller's identity or tenant, or passes through a central authorization check, so no handler can forget it.",
                "steps": ["The attacker signs in with their own account.", "They call GET /api/orders/1001 and see their own order.", "They change the identifier to 1002.", "The server loads order 1002 without an ownership check and returns another customer's data."],
            },
            "code_examples": {"items": [{
                "title": "Order lookup",
                "language": "python",
                "vulnerable": "@app.get(\"/api/orders/<int:order_id>\")\n@login_required\ndef get_order(order_id):\n    order = Order.query.get_or_404(order_id)\n    return jsonify(order.to_dict())",
                "secure": "@app.get(\"/api/orders/<int:order_id>\")\n@login_required\ndef get_order(order_id):\n    order = Order.query.filter_by(id=order_id, owner_id=current_user.id).first()\n    if order is None:\n        abort(404)  # same answer for missing and not-yours\n    return jsonify(order.to_dict())",
                "explanation": "The vulnerable handler checks only that the caller is signed in. The secure handler scopes the query to the caller, so another user's order is indistinguishable from one that does not exist.",
                "security_control": "Object-level authorization",
            }]},
            "attack_surfaces": {"items": [
                {"name": "Identifiers in paths and queries", "weakness_description": "Endpoints accept object identifiers from the client and load records by identifier alone.", "attack_scenario": "An attacker iterates order numbers on GET /api/orders/{id}.", "potential_impact": "Disclosure or modification of other users' records.", "related_vulnerability_classes": ["CWE-639"]},
                {"name": "Identifiers in request bodies and batch operations", "weakness_description": "Bulk or nested operations check the parent object but not each referenced child.", "attack_scenario": "A PATCH request updates the caller's cart but includes another user's address identifier.", "potential_impact": "Cross-account data changes.", "related_vulnerability_classes": ["CWE-639"]},
            ]},
            "mitigations": {"items": [
                {"control": "Scope every data access to the caller", "description": "Filter queries by the authenticated user or tenant, or call a central authorization policy for each object.", "implementation_considerations": "Apply the check in a shared data-access layer rather than per handler.", "validation_guidance": "Run automated tests with two users that try to read and change each other's objects."},
                {"control": "Uniform not-found responses", "description": "Return the same response for missing objects and objects the caller may not access.", "implementation_considerations": "Avoid different status codes or timings that reveal which identifiers exist.", "validation_guidance": "Compare responses for a missing identifier and another user's identifier."},
            ]},
            "architecture": {"diagrams": [
                _seq("Order lookup without an ownership check", "vulnerable", [("attacker", "Attacker (signed in)", "actor"), ("api", "Orders API", "service"), ("db", "Orders database", "datastore")],
                     [("attacker", "api", "GET /api/orders/1002 with own session"), ("api", "db", "SELECT order 1002"), ("db", "api", "Order owned by another user"), ("api", "attacker", "200 OK with another user's order")]),
                _seq("Order lookup scoped to the caller", "secure", [("attacker", "Attacker (signed in)", "actor"), ("api", "Orders API", "service"), ("authz", "Ownership check", "control"), ("db", "Orders database", "datastore")],
                     [("attacker", "api", "GET /api/orders/1002 with own session"), ("api", "authz", "May this user read order 1002?"), ("authz", "db", "SELECT order 1002 AND owner = caller"), ("db", "api", "No matching row"), ("api", "attacker", "404 Not Found")]),
            ]},
        },
        "levels": {
            "junior": ("Explain the difference between authentication and authorization and why changing an identifier can expose data.", "Find IDOR in a test application by replaying requests with a second account."),
            "intermediate": ("Describe object-level, function-level and property-level authorization failures in APIs.", "Write automated two-user tests and fix handlers by scoping queries to the caller."),
            "senior": ("Evaluate authorization models (ownership, RBAC, ABAC) for multi-tenant services.", "Lead reviews that find missing object checks across a codebase and introduce a shared authorization layer."),
            "architect": ("Design central policy enforcement for object access across services.", "Define how identity and tenant context flow through services so every data access can be authorized."),
            "manager": ("Understand IDOR as one of the most common and costly API weaknesses.", "Make authorization tests a release requirement and track findings to closure."),
        },
    },
    {
        "topic_key": "oauth-2-0",
        "name": "OAuth 2.0",
        "aliases": ["OAuth", "OAuth2"],
        "description": "Delegated authorization: an application gets limited access to an API on a user's behalf without the user's password.",
        "placements": [("identity-access-management", "security"), ("cloud-api-security", "security")],
        "relationships": [("api-authorization", "related")],
        "references": [RFC_6749, RFC_7636, RFC_9700],
        "sections": {
            "overview": {
                "short_description": "OAuth 2.0 lets an application call an API for a user with a scoped, short-lived token instead of the user's password.",
                "technical_explanation": "A client redirects the user to an authorization server, which authenticates the user, records consent and returns an authorization code. The client exchanges the code for an access token at the token endpoint. Current best practice (RFC 9700) is the authorization code flow with PKCE for all clients, exact redirect URI matching, and no implicit or password grants.",
                "key_concepts": ["Authorization code flow", "PKCE", "Scopes and audience", "Redirect URI validation", "Refresh tokens"],
                "related_technologies": ["OpenID Connect", "JWT access tokens", "API gateways"],
            },
            "how_it_works": {
                "workflow": "The client sends the user to the authorization endpoint with a code challenge and state. After sign-in, the authorization server redirects back with a code, which the client exchanges, with the code verifier, for an access token.",
                "architecture_explanation": "The authorization server issues tokens; resource servers validate signature, issuer, audience, expiry and scope on every request.",
                "steps": ["Client creates a code verifier, its SHA-256 challenge and a state value.", "User authenticates at the authorization server and consents.", "Authorization server redirects to the registered redirect URI with a code.", "Client checks state and exchanges the code plus verifier for tokens.", "API validates the access token on every call."],
            },
            "code_examples": {"items": [
                {
                    "title": "Starting the authorization request in a browser app",
                    "language": "javascript",
                    "vulnerable": "// Implicit flow: the access token is returned in the URL fragment.\nconst url = new URL(\"https://auth.example.com/authorize\");\nurl.search = new URLSearchParams({\n  response_type: \"token\",\n  client_id: CLIENT_ID,\n  redirect_uri: \"https://app.example.com/callback\",\n  scope: \"orders:read\",\n});\nwindow.location.assign(url);",
                    "secure": "// Authorization code flow with PKCE (RFC 7636) and state.\nconst verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));\nconst digest = await crypto.subtle.digest(\"SHA-256\", new TextEncoder().encode(verifier));\nconst state = base64url(crypto.getRandomValues(new Uint8Array(16)));\nsessionStorage.setItem(\"pkce_verifier\", verifier);\nsessionStorage.setItem(\"oauth_state\", state);\nconst url = new URL(\"https://auth.example.com/authorize\");\nurl.search = new URLSearchParams({\n  response_type: \"code\",\n  client_id: CLIENT_ID,\n  redirect_uri: \"https://app.example.com/callback\",\n  scope: \"orders:read\",\n  state,\n  code_challenge: base64url(new Uint8Array(digest)),\n  code_challenge_method: \"S256\",\n});\nwindow.location.assign(url);",
                    "explanation": "Tokens in URL fragments can leak through history, logs and injected scripts. With PKCE, a stolen authorization code is useless without the verifier, and state ties the response to this browser session.",
                    "security_control": "Authorization code flow with PKCE",
                },
                {
                    "title": "Validating the redirect URI on the authorization server",
                    "language": "python",
                    "vulnerable": "def valid_redirect(client, redirect_uri):\n    # Prefix matching accepts https://app.example.com.evil.net/callback\n    return redirect_uri.startswith(client.redirect_prefix)",
                    "secure": "def valid_redirect(client, redirect_uri):\n    # Exact string comparison against pre-registered URIs (RFC 9700).\n    return redirect_uri in client.registered_redirect_uris",
                    "explanation": "Loose matching lets an attacker register a look-alike URI and receive authorization codes. Compare against registered values exactly.",
                    "security_control": "Exact redirect URI matching",
                },
            ]},
            "attack_surfaces": {"items": [
                {"name": "Authorization code interception", "weakness_description": "Codes delivered to public clients can be intercepted by other apps or scripts.", "attack_scenario": "A malicious app registered for the same custom URI scheme receives the code.", "potential_impact": "Account takeover through token issuance to the attacker.", "related_vulnerability_classes": ["CWE-294"]},
                {"name": "Open or loosely matched redirect URIs", "weakness_description": "The authorization server accepts redirect URIs by prefix or pattern.", "attack_scenario": "The attacker sends a victim an authorization link whose redirect URI points to an attacker-controlled host.", "potential_impact": "Leaked codes or tokens.", "related_vulnerability_classes": ["CWE-601"]},
                {"name": "Tokens accepted without audience checks", "weakness_description": "An API accepts any valid token from the issuer, including tokens meant for other APIs.", "attack_scenario": "A token issued to a low-risk service is replayed against a payments API.", "potential_impact": "Privilege escalation across services.", "related_vulnerability_classes": ["CWE-285"]},
            ]},
            "mitigations": {"items": [
                {"control": "PKCE for every client", "description": "Bind the authorization code to a verifier only the requesting client holds.", "implementation_considerations": "Use S256; reject plain challenges.", "validation_guidance": "Confirm the token endpoint rejects a code without the matching verifier."},
                {"control": "Exact redirect URI matching", "description": "Register full redirect URIs and compare them exactly.", "implementation_considerations": "Disallow wildcards; review registrations regularly.", "validation_guidance": "Attempt authorization with modified hosts, paths and query strings."},
                {"control": "Audience and scope validation at the API", "description": "Resource servers check issuer, audience, expiry and scope on every request.", "implementation_considerations": "Use short-lived access tokens and sender-constrained tokens where possible.", "validation_guidance": "Replay a token issued for another audience and expect rejection."},
            ]},
            "architecture": {"diagrams": [
                _seq("Implicit flow exposes the access token", "vulnerable", [("spa", "Browser app", "service"), ("as", "Authorization server", "service"), ("script", "Injected script", "actor"), ("api", "Orders API", "service")],
                     [("spa", "as", "Authorize with response_type=token"), ("as", "spa", "Access token in URL fragment"), ("script", "spa", "Read token from the URL"), ("script", "api", "Call the API with the stolen token")]),
                _seq("Authorization code flow with PKCE", "secure", [("spa", "Browser app", "service"), ("as", "Authorization server", "service"), ("api", "Orders API", "service")],
                     [("spa", "as", "Authorize with code_challenge and state"), ("as", "spa", "Authorization code to the registered URI"), ("spa", "as", "Code plus code_verifier at the token endpoint"), ("as", "spa", "Short-lived, audience-bound access token"), ("spa", "api", "API call with the bearer token")]),
            ]},
        },
        "levels": {
            "junior": ("Explain the roles in OAuth 2.0 and why the authorization code flow is used.", "Configure a client with PKCE against a test authorization server."),
            "intermediate": ("Describe PKCE, state, scopes and token validation.", "Implement token validation in an API and test redirect URI handling."),
            "senior": ("Assess OAuth deployments against RFC 9700, including token lifetimes and sender-constrained tokens.", "Review integrations for redirect, code interception and audience flaws and lead remediation."),
            "architect": ("Design token architecture across services: issuers, audiences, scopes and trust boundaries.", "Define standards for client registration, token formats and validation that teams adopt."),
            "manager": ("Understand the business risk of delegated access and third-party integrations.", "Require security review for new OAuth clients and track their lifecycle."),
        },
    },
    {
        "topic_key": "ssrf",
        "name": "Server-Side Request Forgery (SSRF)",
        "aliases": ["SSRF", "Server-Side Request Forgery"],
        "description": "Making a server send requests to destinations the attacker chooses, including internal services.",
        "placements": [("cloud-api-security", "vulnerabilities"), ("web-application-security", "vulnerabilities")],
        "relationships": [("idor-bola", "related")],
        "references": [OWASP_API7, CWE_918, OWASP_SSRF, AWS_IMDS],
        "sections": {
            "overview": {
                "short_description": "An attacker gets the server to fetch a URL of their choosing, reaching internal systems the attacker cannot reach directly.",
                "technical_explanation": "Features that fetch remote resources (previews, webhooks, imports, PDF rendering) become a proxy into the server's network when the destination is not restricted. In cloud environments the instance metadata endpoint at 169.254.169.254 is a common target because it can return temporary credentials.",
                "key_concepts": ["Destination allow-lists", "DNS resolution and rebinding", "Redirect handling", "Cloud instance metadata", "Egress filtering"],
                "related_technologies": ["Cloud metadata services", "Webhooks", "HTTP client libraries"],
            },
            "how_it_works": {
                "workflow": "The application accepts a URL from the user and fetches it from the server. The attacker supplies an internal address, and the response or its side effects come back to the attacker.",
                "architecture_explanation": "Defence is layered: validate the destination in the application, block private and link-local ranges at the network egress, and harden metadata services (for example, AWS IMDSv2 session tokens).",
                "steps": ["The attacker submits a URL to a feature that fetches remote content.", "The server resolves and requests the URL from inside the network.", "The internal service answers the trusted server.", "The application returns the content, or acts on it, revealing internal data."],
            },
            "code_examples": {"items": [{
                "title": "Link preview endpoint",
                "language": "python",
                "vulnerable": "@app.post(\"/api/preview\")\ndef preview():\n    url = request.json[\"url\"]\n    response = requests.get(url, timeout=5)\n    return {\"status\": response.status_code, \"body\": response.text[:500]}",
                "secure": "ALLOWED_HOSTS = {\"images.example-cdn.com\"}\n\n@app.post(\"/api/preview\")\ndef preview():\n    url = urlparse(request.json[\"url\"])\n    if url.scheme != \"https\" or url.hostname not in ALLOWED_HOSTS:\n        abort(400)\n    address = ipaddress.ip_address(socket.gethostbyname(url.hostname))\n    if address.is_private or address.is_loopback or address.is_link_local:\n        abort(400)\n    response = requests.get(url.geturl(), timeout=5, allow_redirects=False)\n    return {\"status\": response.status_code}",
                "explanation": "The secure version allows only known hosts over HTTPS, refuses private, loopback and link-local addresses (which include 169.254.169.254), and does not follow redirects. To defeat DNS rebinding, connect to the resolved address rather than resolving again, and enforce the same rules with egress filtering.",
                "security_control": "Destination allow-list with resolved-address checks",
            }]},
            "attack_surfaces": {"items": [
                {"name": "URL-fetching features", "weakness_description": "Previews, imports, webhooks and renderers fetch user-supplied URLs.", "attack_scenario": "The attacker submits http://169.254.169.254/ to a preview feature.", "potential_impact": "Theft of cloud credentials or access to internal services.", "related_vulnerability_classes": ["CWE-918"]},
                {"name": "Redirects and DNS tricks", "weakness_description": "Validation checks the first URL but the client follows redirects or re-resolves DNS.", "attack_scenario": "An allowed host redirects to an internal address.", "potential_impact": "Bypass of URL validation.", "related_vulnerability_classes": ["CWE-918"]},
            ]},
            "mitigations": {"items": [
                {"control": "Destination allow-list", "description": "Permit only the schemes, hosts and ports a feature needs.", "implementation_considerations": "Prefer allow-lists to block-lists; disable redirects or re-validate each hop.", "validation_guidance": "Test with internal IP addresses, alternative IP encodings and redirecting hosts."},
                {"control": "Network egress controls", "description": "Block outbound requests from application servers to private, loopback and metadata ranges.", "implementation_considerations": "Route required outbound traffic through a proxy that enforces policy.", "validation_guidance": "Confirm from the application host that internal ranges are unreachable."},
                {"control": "Harden the metadata service", "description": "Require session tokens for instance metadata (for example, AWS IMDSv2) and limit hop count.", "implementation_considerations": "Enforce through infrastructure policy so new instances inherit it.", "validation_guidance": "Verify that metadata requests without a token fail."},
            ]},
            "architecture": {"diagrams": [
                _seq("Preview feature reaches the metadata service", "vulnerable", [("attacker", "Attacker", "actor", "internet"), ("app", "Preview service", "service", "vpc"), ("metadata", "Instance metadata service", "service", "vpc")],
                     [("attacker", "app", "POST /api/preview with an internal metadata URL"), ("app", "metadata", "GET credentials path"), ("metadata", "app", "Temporary cloud credentials"), ("app", "attacker", "Credentials echoed in the preview")],
                     kind="trust_boundary", boundaries=[("internet", "Internet"), ("vpc", "Cloud network")]),
                _seq("Preview feature with destination checks", "secure", [("attacker", "Attacker", "actor", "internet"), ("app", "Preview service", "service", "vpc"), ("guard", "URL allow-list and IP check", "control", "vpc"), ("metadata", "Instance metadata service", "service", "vpc")],
                     [("attacker", "app", "POST /api/preview with an internal metadata URL"), ("app", "guard", "Validate scheme, host and resolved address"), ("guard", "app", "Rejected: link-local address"), ("app", "attacker", "400 Bad Request")],
                     kind="trust_boundary", boundaries=[("internet", "Internet"), ("vpc", "Cloud network")]),
            ]},
        },
        "levels": {
            "junior": ("Explain what SSRF is and why internal addresses are dangerous targets.", "Reproduce SSRF in a lab against a mock metadata endpoint."),
            "intermediate": ("Describe bypasses such as redirects, DNS rebinding and alternative IP encodings.", "Implement and test destination validation for a URL-fetching feature."),
            "senior": ("Assess SSRF exposure across services and cloud metadata configuration.", "Lead layered fixes combining application checks, egress controls and metadata hardening."),
            "architect": ("Design egress architecture so application tiers cannot reach sensitive internal endpoints.", "Define a shared outbound HTTP client and proxy policy for all services."),
            "manager": ("Understand SSRF as a path from a web feature to cloud credential theft.", "Prioritise egress controls and metadata hardening across teams."),
        },
    },
    {
        "topic_key": "secure-boot",
        "name": "Secure Boot",
        "aliases": [],
        "description": "Each boot stage verifies the next before running it, from an immutable root of trust.",
        "placements": [("boot-security", "security")],
        "relationships": [("chain-of-trust", "dependency"), ("hardware-root-of-trust", "dependency"), ("firmware-signature-verification", "dependency")],
        "references": [NIST_193, NIST_147, UEFI_SPECS, NVD_BOOTHOLE],
        "sections": {
            "overview": {
                "short_description": "Secure Boot lets a device run only boot software signed by a trusted key, so tampered bootloaders and kernels are refused.",
                "technical_explanation": "An immutable first stage (boot ROM or platform firmware) holds or references trusted keys and verifies the signature of the next stage before executing it. Each stage repeats this for the stage after it, forming a chain of trust. Anti-rollback counters stop signed but vulnerable older images from being reinstalled.",
                "key_concepts": ["Root of trust", "Chain of trust", "Signature verification", "Anti-rollback", "Key revocation"],
                "related_technologies": ["UEFI Secure Boot", "TPM measured boot", "ARM Trusted Firmware"],
            },
            "how_it_works": {
                "workflow": "On reset the boot ROM verifies the first-stage bootloader against a key anchored in hardware, then each stage verifies the next until the operating system kernel runs.",
                "architecture_explanation": "Trust starts in hardware the attacker cannot change (ROM, fuses). Everything that can be updated must be verified by something that cannot.",
                "steps": ["Boot ROM reads the trusted key hash from fuses.", "It verifies the first-stage bootloader signature and version.", "The bootloader verifies the next stage the same way.", "Only verified code runs; anything else stops the boot or enters recovery."],
            },
            "attack_surfaces": {"items": [
                {"name": "Unverified data parsed by verified code", "weakness_description": "A signed bootloader parses configuration or images that are not signed.", "attack_scenario": "A crafted configuration file triggers a memory-safety bug in the bootloader.", "potential_impact": "Code execution before the OS, bypassing Secure Boot.", "related_vulnerability_classes": ["CWE-120"]},
                {"name": "Rollback to vulnerable signed images", "weakness_description": "Old images remain validly signed after a vulnerability is fixed.", "attack_scenario": "An attacker installs an older signed bootloader with a known flaw.", "potential_impact": "Reintroduction of a fixed vulnerability.", "related_vulnerability_classes": ["CWE-1328"]},
            ]},
            "mitigations": {"items": [
                {"control": "Anti-rollback counters and revocation", "description": "Store a minimum security version in monotonic storage and maintain revocation lists for compromised images.", "implementation_considerations": "Plan key and revocation updates as part of the release process.", "validation_guidance": "Attempt to boot an older signed image and expect refusal."},
                {"control": "Sign or authenticate all boot inputs", "description": "Verify configuration and modules loaded during boot, not only executables.", "implementation_considerations": "Minimise parsing in early boot stages and use memory-safe parsers.", "validation_guidance": "Fuzz boot-time parsers and test with modified configuration files."},
            ]},
            "real_world_examples": {"items": [{
                "cve_identifier": "CVE-2020-10713",
                "advisory_or_research_title": "BootHole: GRUB2 configuration parsing buffer overflow",
                "affected_product": "GRUB2 bootloader",
                "description": "A buffer overflow while parsing grub.cfg allows arbitrary code execution in a signed bootloader, bypassing UEFI Secure Boot.",
                "weakness": "CWE-120",
                "impact": "Code execution during boot before the operating system starts.",
                "remediation": "Update GRUB2 and shims, and update the UEFI revocation list (dbx).",
                "exploitation_status": "publicly_disclosed",
                "verification_status": "unverified",
                "reference": NVD_BOOTHOLE["url"],
            }]},
            "architecture": {"diagrams": [
                _seq("Signed bootloader parses an unsigned configuration", "vulnerable", [("rom", "Platform firmware", "control", "anchor"), ("loader", "Signed bootloader", "service"), ("config", "Unsigned boot configuration", "datastore"), ("kernel", "Kernel", "service")],
                     [("rom", "loader", "Verify bootloader signature"), ("loader", "config", "Parse configuration file"), ("config", "loader", "Crafted input overflows the parser"), ("loader", "kernel", "Attacker code runs before the OS")],
                     kind="attack_path", boundaries=[("anchor", "Hardware trust anchor")]),
                _seq("Every stage verifies the next", "secure", [("rom", "Boot ROM", "control", "anchor"), ("fuses", "Key hash in fuses", "datastore", "anchor"), ("bl1", "First-stage bootloader", "service"), ("bl2", "Second-stage bootloader", "service"), ("kernel", "Kernel", "service")],
                     [("rom", "fuses", "Read trusted key hash"), ("rom", "bl1", "Verify signature and version, then run"), ("bl1", "bl2", "Verify signature and version, then run"), ("bl2", "kernel", "Verify signature, then hand over")],
                     kind="architecture", boundaries=[("anchor", "Hardware trust anchor")]),
            ]},
        },
        "levels": {
            "junior": ("Explain the chain of trust and why the first stage must be immutable.", "Inspect a device's Secure Boot state and the keys it trusts."),
            "intermediate": ("Describe signature verification, anti-rollback and key revocation.", "Configure Secure Boot on a development board and test refusal of unsigned images."),
            "senior": ("Assess boot chains for unverified inputs, rollback and key management weaknesses.", "Lead boot security reviews and threat models for a product line."),
            "architect": ("Design root-of-trust, key hierarchy and update strategy across the device lifecycle.", "Define signing infrastructure, revocation and recovery procedures."),
            "manager": ("Understand Secure Boot as a product security and supply-chain requirement.", "Ensure signing keys, revocation and boot updates are owned and resourced."),
        },
    },
    {
        "topic_key": "firmware-signature-verification",
        "name": "Firmware Signature Verification",
        "aliases": ["Firmware signing", "Signed firmware updates"],
        "description": "Checking that firmware was signed by a trusted key and is not a rollback before installing or running it.",
        "placements": [("boot-security", "security")],
        "relationships": [("cryptographic-key-management", "dependency"), ("secure-boot", "related")],
        "references": [NIST_193, RFC_9019, RFC_9124],
        "sections": {
            "overview": {
                "short_description": "Devices accept firmware only if its signature verifies against a trusted public key and its version is not older than allowed.",
                "technical_explanation": "The image digest is signed with a private key kept in a hardware security module. The device holds the public key (or its hash) in immutable storage, verifies the signature over the exact bytes it will run, checks a security version against an anti-rollback counter, and only then writes or executes the image.",
                "key_concepts": ["Digital signatures", "Image manifests", "Anti-rollback", "Key storage", "Time-of-check to time-of-use"],
                "related_technologies": ["ECDSA and Ed25519", "SUIT manifests", "Hardware security modules"],
            },
            "how_it_works": {
                "workflow": "The build system hashes and signs the image. The device receives the image, copies it to memory it controls, verifies the signature and version, and installs or boots it only if both pass.",
                "architecture_explanation": "Verification must happen on the same bytes that will be executed, in memory an attacker cannot change between check and use.",
                "steps": ["Copy the image into internal memory.", "Hash the payload.", "Verify the signature with the key anchored in ROM or fuses.", "Compare the security version with the rollback counter.", "Install or execute only after both checks pass."],
            },
            "code_examples": {"items": [{
                "title": "Bootloader image check",
                "language": "c",
                "vulnerable": "int load_image(const struct fw_image *img) {\n    /* Checks only that the header looks right. */\n    if (img->header.magic != FW_MAGIC)\n        return -1;\n    jump_to(img->payload);\n    return 0;\n}",
                "secure": "int load_image(const struct fw_image *img) {\n    uint8_t digest[32];\n    if (img->header.magic != FW_MAGIC || img->header.payload_len > MAX_PAYLOAD)\n        return -1;\n    sha256(img->payload, img->header.payload_len, digest);\n    /* Public key lives in ROM or fuses, never in the updatable image. */\n    if (!ecdsa_p256_verify(ROM_PUBLIC_KEY, digest, img->header.signature))\n        return -1;\n    /* Anti-rollback: refuse images older than the monotonic counter. */\n    if (img->header.security_version < read_rollback_counter())\n        return -1;\n    jump_to(img->payload);\n    return 0;\n}",
                "explanation": "The secure version bounds the length, verifies the signature with a key the attacker cannot replace and refuses older images. Run it on a copy in internal memory so the image cannot change between the check and the jump.",
                "security_control": "Signature and anti-rollback verification",
            }]},
            "attack_surfaces": {"items": [
                {"name": "Unsigned or partially verified updates", "weakness_description": "The updater checks headers or checksums instead of signatures, or verifies only part of the image.", "attack_scenario": "An attacker supplies a modified image with a valid header.", "potential_impact": "Persistent malicious firmware.", "related_vulnerability_classes": ["CWE-347"]},
                {"name": "Check-then-use on external flash", "weakness_description": "The image is verified in external flash and then read again for execution.", "attack_scenario": "An attacker swaps flash contents after verification.", "potential_impact": "Execution of unverified code.", "related_vulnerability_classes": ["CWE-367"]},
            ]},
            "mitigations": {"items": [
                {"control": "Verify signatures with an immutable key", "description": "Anchor the verification key in ROM or fuses and verify over the full image.", "implementation_considerations": "Plan key rotation with multiple key slots or key revocation.", "validation_guidance": "Flip one byte of a signed image and confirm it is rejected."},
                {"control": "Verify the bytes you run", "description": "Copy to internal memory before verifying and executing.", "implementation_considerations": "Lock the memory region after verification.", "validation_guidance": "Review the boot flow for re-reads from external storage."},
                {"control": "Anti-rollback", "description": "Refuse images whose security version is below a monotonic counter.", "implementation_considerations": "Increment the counter only after the new image boots successfully.", "validation_guidance": "Attempt to install an older signed image."},
            ]},
            "architecture": {"diagrams": [
                _seq("Update accepted on header checks only", "vulnerable", [("attacker", "Attacker update package", "external"), ("updater", "Device updater", "service"), ("flash", "Firmware flash", "datastore")],
                     [("attacker", "updater", "Image with a valid header and modified payload"), ("updater", "flash", "Write the image"), ("flash", "updater", "Modified firmware runs on next boot")], kind="flow"),
                _seq("Update verified before installation", "secure", [("package", "Signed update package", "external"), ("updater", "Device updater", "service"), ("verify", "Signature check with ROM key", "control"), ("counter", "Rollback counter", "datastore"), ("flash", "Firmware flash", "datastore")],
                     [("package", "updater", "Image and signed manifest"), ("updater", "verify", "Hash the payload and verify the signature"), ("verify", "counter", "Check security version"), ("verify", "flash", "Write only verified, current images")], kind="flow"),
            ]},
        },
        "levels": {
            "junior": ("Explain digital signatures and why checksums are not enough.", "Verify a signed firmware image with command-line tools."),
            "intermediate": ("Describe manifests, anti-rollback and time-of-check to time-of-use risks.", "Implement and test signature verification in a bootloader or updater."),
            "senior": ("Assess firmware update pipelines end to end, from build signing to device verification.", "Lead reviews of key storage, signing services and verification code."),
            "architect": ("Design signing key hierarchies, rotation and revocation for a fleet.", "Define update architecture (for example, SUIT manifests) across product lines."),
            "manager": ("Understand firmware signing as a supply-chain and regulatory expectation.", "Ensure signing keys are protected and update processes are audited."),
        },
    },
]

# Recorded in the change reason of the relevant proposals.
EXAMPLE_NOTES = {
    "idor-bola": "No real-world example included: no specific CVE was selected with a citable advisory; add one after verification.",
    "oauth-2-0": "No real-world example included: add a verified advisory if one is needed.",
    "ssrf": "No real-world example included: add a verified advisory or CISA KEV entry if one is needed.",
    "firmware-signature-verification": "No real-world example included: add a verified advisory if one is needed.",
    "secure-boot": "The CVE-2020-10713 example cites NVD and needs a verified source before publication.",
}

# Branches proposed for existing published topics (--place-existing). Topics not listed default to "security"
# in every domain they are already linked to. Unlinked topics get the domains listed in EXISTING_UNLINKED.
EXISTING_FOUNDATIONS = {"chain-of-trust", "hardware-root-of-trust", "cryptographic-key-management", "threat-modeling"}
EXISTING_UNLINKED = {"chain-of-trust": ["boot-security"], "kubernetes-security": ["cloud-infrastructure-security"]}
