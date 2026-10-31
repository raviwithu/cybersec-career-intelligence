# AWS Knowledge Map Content Analysis

Status: **draft for review, nothing has been added to the application yet.**
Prepared: 2026-10-31

## 1. Source material

Folder: `/mnt/usbdrive2/Work/Data/Training/Cloud/AWS/PenAcad/2021/AWSBootCamp/`
Course: Pentester Academy, *AWS Cloud Security: Beginner Edition* (Jeswin Mathai), 2021.

| File | Pages | Coverage | How it was read |
|---|---|---|---|
| `AWS_Cloud_Security___Week_I.pdf` | 75 | AWS overview, IAM concepts, policies, policy evaluation, CLI, assessment tools, Labs 1–6 | Rendered slide images (text layer is not extractable) |
| `AWS_Cloud_Security_Week_II.pdf` | 64 | Cross-account enumeration, IAM privilege escalation, Lambda roles, VPC, EC2, CloudFormation, Access Analyzer, API Gateway, Labs 7–22 | Extracted text |
| `AWS_Cloud_Security_Week_III.pdf` | 70 | Lambda internals, layers, runtimes, command injection, deserialization, SSRF, XXE, alias routing, Labs 23–31 | Extracted text |

References below use `W1 s18` = Week 1, slide 18, and `Lab n` = the course lab number.

Items marked **(beyond the course)** are standard AWS security features that the PDFs do not cover. They are listed so each Security branch is complete; keep or drop them during review.

## 2. Proposed structure

The map nests domains to any depth, and every domain has three branches: **Foundations**, **Security** (the service's built-in security features and how to configure them) and **Common Vulnerabilities**. Topics can also have child topics.

```
Cloud Infrastructure Security          (existing top-level domain)
└── AWS                                (existing sub-domain, id 23)
    ├── AWS IAM                        (new sub-domain)
    ├── AWS Lambda                     (new sub-domain)
    ├── Amazon API Gateway             (new sub-domain)
    └── Amazon EC2 and VPC             (new sub-domain)
```

Sub-domain names carry an "AWS" or "Amazon" prefix because domain names are unique across the whole application, and a bare "IAM" would be confused with the existing top-level **Identity and Access Management** domain.

In the lists below, an indented item is a **child topic** of the item above it.

### 2.1 Shared vulnerability topics (reused, never copied)

Generic vulnerability classes are created **once** as a single topic and **placed** in every domain where they apply. Each placement can carry a **domain context note** that says how the vulnerability shows up in that domain. The topic's description, sections, code examples and career levels are shared by every placement; only the note differs per domain. Items marked *(shared)* in sections 3–7 are these topics.

| Shared topic | AWS placements (from the course) | Other domains it fits (suggested, not from the course) | Example context note for an AWS placement |
|---|---|---|---|
| Server-Side Request Forgery (SSRF), reuse proposal #5973 | AWS Lambda, Amazon EC2 and VPC | Web Application Security, Cloud API Security | Lambda: `file://` reads of local files and environment variables. EC2: stealing role credentials from the instance metadata service. |
| XML External Entity (XXE) Injection | AWS Lambda | Web Application Security, Cloud API Security | Python and PHP runtimes parsing untrusted XML. |
| Insecure Deserialization | AWS Lambda | Web Application Security | Python pickle in a cookie leads to code execution inside the function. |
| Command Injection | AWS Lambda | Web Application Security, Embedded Application Security | Shell calls in function code expose the execution role's credentials in environment variables. |
| HTTP Verb Tampering | Amazon API Gateway | Web Application Security | Methods without authorization configured on a resource. |
| Missing Authentication on Endpoints | Amazon API Gateway | Cloud API Security, Web Application Security | API Gateway methods with authorization set to NONE. |
| Denial of Service and Missing Throttling | Amazon API Gateway | Cloud API Security | No usage plan or stage throttling limits. |
| Leaked Cloud Access Keys | AWS IAM | DevSecOps | AWS access keys committed to GitHub. |
| Publicly Exposed Cloud Storage | AWS (whole platform) | Cloud Infrastructure Security | Public S3 buckets and bucket policies. |

These stay AWS-specific (placed only under AWS): IAM Privilege Escalation and its child topics, Unauthenticated Cross-Account User and Role Enumeration, Misconfigured Private API Gateway Resource Policy, Poor Lambda Authorizer Logic, Weak IAM-Based Authentication, Lambda Runtime API Abuse, Credential Theft via the EC2 Instance Metadata Service.

How it is added in the app (implemented):
- **Place topic** accepts several domains at once and an optional note; each domain becomes its own reviewable proposal.
- **Domain context** on a placed topic edits the note for that domain only.
- **New topic** can carry a note for its first placement.
- The topic panel shows the note for the domain being viewed and lists every other domain the topic appears in, with that domain's note.

---

## 3. AWS (whole platform)

### Foundations
- **Amazon Web Services Overview**: 200+ services, global footprint, customer types (W1 s12)
- **Data Centers vs Cloud** (W1 s16)
- **AWS CloudFormation**: YAML/JSON templates, stacks created as the current user or an assumed role (W2)

### Security
- **Shared Responsibility Model**: what AWS secures vs what the customer secures **(beyond the course)**
- **Multi-Account Security with AWS Organizations**: separate accounts per environment, central guardrails through SCPs (W1 s55–57, W2)
- **Resource Policy Guardrails**: explicit Deny and Conditions to block public access, as in the S3 bucket policy examples (W1 s53–54)

### Common Vulnerabilities
- **Publicly Exposed Cloud Storage** *(shared)*: AWS context: real breaches (Accenture, Capital One, Time Warner Cable, Uber and others), public bucket search engines such as GrayhatWarfare (W1 s13–15)

---

## 4. AWS › AWS IAM

### Foundations
- **IAM Overview** (W1 s11, s17)
  - **IAM Hierarchy & Groups**: account → groups (Admins, Developers, Test) → users (W1 s18)
  - **IAM Components**: users, groups, roles, policies (W1 s19)
- **IAM Elements** (W1 s23–26)
  - **Principal**: root user, IAM user, IAM role
  - **Request**: actions, resources, principal, environment, resource data
  - **Authentication**: console (email or username + password + account ID), API/CLI (access key + secret key)
  - **Authorization**: request context checked against applicable policies
  - **Actions or Operations**: the actions a service defines for each resource
  - **Resources**: objects that exist within a service
- **IAM Users**: individual or service identity, console and programmatic access, MFA, long-term credentials, single account (W1 s20, s27)
- **IAM Groups**: collection of users, policies apply to all members, a user can be in multiple groups (W1 s28)
- **IAM Roles** (W1 s31–36)
  - **Assuming a Role and Switch Role**: trusted resources assume roles directly; Switch Role for console access
  - **Trust Policy vs Permissions Policy**: who can assume the role vs what the role can do
  - **Temporary Credentials**: valid 1 to 12 hours (default 1 hour)
- **Amazon Resource Names (ARNs)**: format, partition, service, region, account ID, resource ID, examples (W1 s37–38)
- **IAM Policies** (W1 s39–58)
  - **Policy Types**: identity-based, resource-based, permissions boundaries, SCPs, ACLs, session policies
  - **Identity-based Policies**: AWS managed, customer managed, inline
  - **Resource-based Policies**: attached to resources, grant a principal actions on that resource, not supported by every service
  - **JSON Policy Structure**: Version, Statement, Sid, Effect, Principal, Action, Resource, Condition
  - **Permissions Boundaries**
  - **Service Control Policies (SCPs)**
  - **Access Control Lists (ACLs)**
  - **Session Policies**
- **Policy Evaluation Logic**: default deny, explicit allow, boundaries/SCPs/session policies must all allow, explicit deny wins (W1 s25, s59–60)
- **AWS Organizations Hierarchy**: root, organizational units, management and member accounts, cross-account access (W1 s55–56, W2)
- **AWS CLI/SDK Access**: access key ID, secret access key, session token, CLI installation and reference (W1 s63–65)

### Security
- **Least Privilege with IAM Policies**: specific Actions and Resources instead of wildcards (W1 s43–46)
- **Policy Conditions**: restrict by MFA, principal tags, source VPC or IP (W1 s44–45, s62)
- **Multi-Factor Authentication**: for console users and for role assumption (W1 s27, s62)
- **Temporary Credentials with Roles**: prefer roles over long-term access keys, limit session duration (W1 s31–33)
- **Role Trust Policy Hardening**: allow only specific principals, require MFA or other conditions (W1 s61–62, W2)
- **Permissions Boundaries**: cap what a user or role can ever be granted (W1 s57, s59)
- **Service Control Policies**: organization-wide maximum permissions, including the root user of member accounts (W1 s57)
- **Session Policies**: narrow the permissions of a single role session (W1 s57–58)
- **Explicit Deny and Evaluation Order**: an explicit deny always overrides allows (W1 s25, s60)
- **Groups for Permission Management**: attach policies to groups rather than individual users (W1 s28)
- **IAM Access Analyzer**: finds S3 buckets, roles, KMS keys, Lambda functions and layers, SQS queues and secrets shared with external principals (W2)
- **Root User Protection, Credential Rotation and Password Policy** **(beyond the course)**

### Common Vulnerabilities
- **Leaked Cloud Access Keys** *(shared)*: keys committed to GitHub and other public sources (W1 s21–22)
- **Unauthenticated Cross-Account User and Role Enumeration**: confirming accounts, users and roles through trust policy updates in an attacker account (W2, Lab 7)
- **IAM Privilege Escalation** (W2)
  - **Misconfigured Trust Policy** (Lab 8)
  - **Overly Permissive IAM Permissions**: `iam:PutGroupPolicy`, `iam:PutRolePolicy`, `iam:PutUserPolicy`, `iam:AttachGroupPolicy`, `iam:AttachRolePolicy`, `iam:AttachUserPolicy`, `iam:CreatePolicyVersion`, `iam:SetDefaultPolicyVersion`, `iam:AddUserToGroup`, `iam:CreateLoginProfile`, `iam:UpdateLoginProfile`, `iam:CreateAccessKey` (Labs 9–10)
  - **Dangerous Policy Combinations** (Labs 11–12)
  - **iam:PassRole Abuse**: through Lambda, EC2 and CloudFormation (Labs 13–15)

---

## 5. AWS › AWS Lambda

### Foundations
- **Serverless vs Traditional Architecture**: LAMP stack vs serverless PHP stack (W1 s29–30, W3)
- **AWS Lambda Overview**: function code, scaling, pay per time and memory, throttling (W2, W3)
- **Lambda Execution Environment**: lifecycle, read-only file system, 512 MB `/tmp`, inbound connections blocked, outbound TCP only, 15-minute maximum, parallel invocations (W3)
- **Lambda Invocations and Destinations** (W3)
- **Lambda Layers**: up to 5 versions, immutable, extracted to `/opt`, stacking order, per-runtime library paths, layer ARNs (W3)
- **Lambda Environment Variables** (W3)
- **Lambda Execution Role** (W1 s34, W2)
- **Lambda Alias Routing** (W3)
- **Lambda Runtimes and Runtime API**: `/var/runtime`, custom runtimes with `bootstrap`, `_HANDLER`, `LAMBDA_TASK_ROOT`, `AWS_LAMBDA_RUNTIME_API`, next/response/error endpoints (W3)

### Security
- **Least-Privilege Execution Role**: one role per function, scoped to the resources it needs (W1 s34, W2)
- **Execution Environment Isolation**: read-only file system, inbound connections blocked, time and memory limits (W3)
- **Secrets Handling**: keep credentials out of plain environment variables; encrypted environment variables and Secrets Manager (W3 + **beyond the course**)
- **Restricting Who Can Invoke a Function**: resource-based function policies (W1 s52, W2)
- **Controlling iam:PassRole**: limit which roles can be passed to Lambda (W2)
- **Safe Input Handling in Function Code**: no shell calls with user input, no unpickling of untrusted data, XML parsers with external entities disabled (W3, the defensive side of Labs 25–29)
- **Trusted Layers and Runtimes**: use only trusted layers and pin layer versions (W3)
- **Running Functions inside a VPC** **(beyond the course)**

### Common Vulnerabilities
- **Command Injection** *(shared)*: Lambda context: leads to credential theft from environment variables (Lab 25)
- **Insecure Deserialization** *(shared)*: Python pickle remote code execution through `__reduce__` (Lab 26)
- **Server-Side Request Forgery (SSRF)** *(shared)*: including the `file://` scheme to read local files and environment (Lab 27). **Reuse:** proposal #5973 for this topic is already in review; place it here rather than create a new topic.
- **XML External Entity (XXE) Injection** *(shared)*: Python and PHP runtimes; file reads, SSRF, blind exfiltration (Labs 28–29)
- **Lambda Runtime API Abuse**: retrieving other invocation events from inside the execution environment (Lab 31)

---

## 6. AWS › Amazon API Gateway

### Foundations
- **API Fundamentals**: HTTP, REST and SOAP APIs; request methods; response status codes (W2)
- **API Gateway Overview**: HTTP, REST and WebSocket types; stages, resources and methods; caching; throttling; default and custom domains; service endpoint and `execute-api` URL formats (W2)
- **Private API Gateway** (W2)
- **API Gateway and Lambda Integration**: maximum integration timeout (W3)

### Security
- **HTTPS Enforced by Default** (W2)
- **API Gateway Authentication Options** (W2)
  - **IAM Authorization**: SigV4-signed requests
  - **Lambda Authorizers**: TOKEN and REQUEST types
  - **Amazon Cognito User Pools**
  - **API Keys and Usage Plans**: identify and meter callers; not authentication on their own
- **Resource Policies**: restrict callers by account, IP range, VPC or VPC endpoint (W2)
- **Private APIs with VPC Endpoint Policies**: deny unless the request comes from a specific VPC endpoint (W2, "Expected Resource Policy")
- **Throttling and Rate Limiting** (W2)
- **AWS WAF Integration** (W2)
- **Request Validation and Access Logging** **(beyond the course)**

### Common Vulnerabilities
- **Missing Authentication on Endpoints** *(shared)* (W2)
- **HTTP Verb Tampering** *(shared)* (Lab 18)
- **Misconfigured Private API Gateway Resource Policy**: `Principal: "*"` with `execute-api:Invoke` on all resources (Lab 19)
- **Weak IAM-Based Authentication** (Lab 20)
- **Denial of Service and Missing Throttling** *(shared)* (Lab 21)
- **Poor Lambda Authorizer Logic** (Lab 22)
- **Poorly Configured API Gateway WAF** (W2)

---

## 7. AWS › Amazon EC2 and VPC

### Foundations
- **VPC Components**: subnets, route tables, security groups, endpoints, gateways, network ACLs (W2)
- **VPC Endpoints** (W2)
- **EC2 Instance Profiles**: role-based access for instances; console vs CLI setup steps (W2)
- **EC2 Instance Metadata Service**: `169.254.169.254`; public IP, user data, security groups, instance details, IAM credentials (W2)
- **Accessing EC2 with Systems Manager (SSM)** (W2)

### Security
- **Security Groups**: stateful, instance-level firewall (W2)
- **Network ACLs**: stateless, subnet-level filtering (W2)
- **Private Subnets and Route Tables**: keep workloads off the internet (W2)
- **VPC Endpoints for Private Service Access**: reach AWS services without internet access (W2)
- **Instance Profiles instead of Stored Access Keys** (W2)
- **Session Manager (SSM) instead of Open SSH** (W2)
- **IMDSv2**: session-token metadata service that blocks SSRF credential theft **(beyond the course)**

### Common Vulnerabilities
- **Credential Theft via the EC2 Instance Metadata Service**: reading `iam/security-credentials/` (W2)
- **Server-Side Request Forgery (SSRF)** *(shared, same topic as under AWS Lambda)*: EC2 context: reaching the metadata service to steal role credentials

---

## 8. Tools and enumeration labs (not separate topics)

These stay out of the Security branches. Each is mentioned in the "how it is tested" content of the vulnerability topics it helps find.

| Tool or lab | Mentioned in |
|---|---|
| AWS Console and AWS CLI enumeration (Labs 1–2) | IAM Privilege Escalation, Leaked Cloud Access Keys |
| Pacu (Lab 3) | IAM Privilege Escalation, iam:PassRole Abuse |
| ScoutSuite (Lab 4) | Publicly Exposed Cloud Storage, Misconfigured Private API Gateway Resource Policy |
| PMapper (Lab 5) | IAM Privilege Escalation, Dangerous Policy Combinations |
| enumerate-iam (Lab 6) | Leaked Cloud Access Keys |
| API Gateway enumeration (Labs 16–17) | Missing Authentication on Endpoints |
| Lambda enumeration (Labs 23–24) | Command Injection, Lambda Runtime API Abuse |

## 9. Overlaps with existing content

| Existing item | Status | Recommendation |
|---|---|---|
| Topic proposal #5970 **"AWS"** | Approved, not published | Reject it, as was done for #6047; AWS is now a sub-domain, and publishing this would add a duplicate "AWS" topic |
| Topic proposal #5973 **Server-Side Request Forgery (SSRF)** | In review | Publish it once, then place the same topic under AWS Lambda and Amazon EC2 and VPC (and other domains if wanted), each with its own context note |
| Published topic **API Authorization** | Published | Add a "related" relationship from API Gateway Authentication Options; do not merge |
| Published topic **Penetration Testing** | Published | No change |
| Top-level domain **Identity and Access Management** | Existing | Keep separate; the new sub-domain is named "AWS IAM" to avoid confusion |

## 10. Left out on purpose

- Course administration slides: instructor, conferences, exam, discounts, schedule, communication, VM setup (W1 s1–10, W2 opening slides)
- "Attacking Traditional Architecture", lateral movement and zombie machines (W3): not AWS-specific
- S3 and databases as full sub-domains: named in the course objective but not taught in these three PDFs; only the breach slides cover S3
- Serverless capture-the-flag challenge links (W3)

## 11. Size and how it would be added

| Item | Count |
|---|---|
| New sub-domains | 4 |
| Topics (including child topics) | 112, of which 6 are marked beyond the course (one of them, Secrets Handling, is partly from the course) |

1. Create the four sub-domains under AWS (saved directly, like Add sub-domain).
2. Submit each topic as a proposal with its domain and branch placement and a short description taken from its slides. All proposals go to **Knowledge Review › Mind Map Changes** for review and publication. Nothing is published automatically.
3. After the parent topics are published, submit Set parent topic proposals to link the child topics.
4. Code examples (policy JSON, pickle payloads) and diagrams are **not** included unless requested.

## 12. Decisions needed

1. Keep or drop the items marked **(beyond the course)**.
2. Reject proposal #5970 ("AWS" topic)?
3. Any renames, branch moves, merges or splits in sections 3–7.
