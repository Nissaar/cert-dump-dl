"""
Keyword-based classification of questions into exam domains and topic tags.

ExamTopics doesn't label questions with official exam domains, so we infer them:
  - Domains: one per question, scored from the question stem. The final
    question sentence ("...MOST cost-effectively?") carries extra weight.
  - Topics: multi-label service/area tags, taken from the stem and the
    correct choice(s) only, so distractor choices don't add noise.

Profiles are keyed by exam code. Unknown exams fall back to provider-level
topic maps and get no domains (the HTML hides the domain filter).
"""

import re

# Each rule: (regex, weight). Patterns are case-insensitive unless they start
# with "(?-i)" — used for short acronyms like "S3" or "IAM".
Rule = tuple[str, int]


def _rx(p: str) -> re.Pattern:
    if p.startswith("(?-i)"):
        return re.compile(p[5:])
    return re.compile(p, re.IGNORECASE)


# ─────────────────────────────────────────────
#  TOPIC MAPS
# ─────────────────────────────────────────────

AWS_TOPICS: dict[str, list[str]] = {
    "Compute": [r"(?-i)\bEC2\b", r"\bLambda\b", r"\bAuto Scaling\b", r"Elastic Beanstalk",
                r"\bAWS Batch\b", r"\bLightsail\b", r"\bOutposts\b", r"(?-i)\bAMIs?\b"],
    "Containers": [r"(?-i)\bECS\b", r"(?-i)\bEKS\b", r"\bFargate\b", r"(?-i)\bECR\b",
                   r"\bcontaineri[sz]ed\b", r"\bcontainers?\b", r"\bKubernetes\b", r"\bDocker\b"],
    "Storage": [r"(?-i)\bS3\b", r"(?-i)\bEBS\b", r"(?-i)\bEFS\b", r"\bFSx\b", r"Storage Gateway",
                r"\bGlacier\b", r"\bAWS Backup\b", r"\bSnowball\b", r"\bSnowcone\b",
                r"\bSnow Family\b", r"\bInstance Store\b"],
    "Databases": [r"(?-i)\bRDS\b", r"\bAurora\b", r"\bDynamoDB\b", r"\bElastiCache\b",
                  r"\bRedshift\b", r"\bNeptune\b", r"\bDocumentDB\b", r"\bKeyspaces\b",
                  r"\bMemoryDB\b", r"\bdatabases?\b", r"\bSQL Server\b", r"\bPostgreSQL\b",
                  r"\bMySQL\b", r"\bOracle\b"],
    "Networking & CDN": [r"(?-i)\bVPCs?\b", r"\bsubnets?\b", r"\bRoute 53\b", r"\bCloudFront\b",
                         r"\bGlobal Accelerator\b", r"\bDirect Connect\b", r"(?-i)\bVPN\b",
                         r"\bTransit Gateway\b", r"(?-i)\bNAT\b", r"\bload balancers?\b",
                         r"(?-i)\b(ALB|NLB|ELB)\b", r"\bPrivateLink\b", r"\bVPC endpoints?\b",
                         r"\bpeering\b", r"\bInternet gateway\b"],
    "Security & Identity": [r"(?-i)\bIAM\b", r"(?-i)\bKMS\b", r"Secrets Manager", r"\bCognito\b",
                            r"(?-i)\bWAF\b", r"\bShield\b", r"\bGuardDuty\b", r"\bMacie\b",
                            r"\bInspector\b", r"\bSecurity Hub\b", r"Certificate Manager",
                            r"(?-i)\bACM\b", r"\bencrypt", r"\bSCPs?\b", r"\bIdentity Center\b",
                            r"\bsecurity groups?\b", r"\bnetwork ACLs?\b", r"\bCloudHSM\b",
                            r"\bDirectory Service\b", r"\bActive Directory\b", r"\bFirewall Manager\b",
                            r"\bNetwork Firewall\b"],
    "App Integration": [r"(?-i)\bSQS\b", r"(?-i)\bSNS\b", r"\bEventBridge\b", r"\bStep Functions\b",
                        r"\bAPI Gateway\b", r"\bAmazon MQ\b", r"\bAppSync\b", r"\bdecoupl",
                        r"\bSimple Queue Service\b", r"\bSimple Notification Service\b"],
    "Analytics": [r"\bKinesis\b", r"\bAthena\b", r"\bAWS Glue\b", r"\bGlue\b", r"(?-i)\bEMR\b",
                  r"\bQuickSight\b", r"\bOpenSearch\b", r"\bLake Formation\b", r"(?-i)\bMSK\b",
                  r"\bdata lake\b", r"\bKafka\b"],
    "Management & Monitoring": [r"\bCloudWatch\b", r"\bCloudTrail\b", r"\bAWS Config\b",
                                r"\bSystems Manager\b", r"\bCloudFormation\b", r"\bTrusted Advisor\b",
                                r"\bControl Tower\b", r"\bService Catalog\b", r"\bOrganizations\b",
                                r"\bX-Ray\b", r"\bHealth Dashboard\b", r"\bAWS Health\b"],
    "Migration & Transfer": [r"(?-i)\bDMS\b", r"Database Migration Service", r"Application Migration Service",
                             r"\bDataSync\b", r"\bTransfer Family\b", r"\bmigrat", r"\bSnowball\b",
                             r"\bSchema Conversion\b"],
    "Cost Management": [r"\bCost Explorer\b", r"\bAWS Budgets\b", r"\bSavings Plans?\b",
                        r"\bReserved Instances?\b", r"\bSpot Instances?\b", r"\bCompute Optimizer\b",
                        r"Cost and Usage Report", r"\bcost allocation tags?\b", r"\bPricing Calculator\b"],
    "Machine Learning": [r"\bSageMaker\b", r"\bRekognition\b", r"\bComprehend\b", r"\bTextract\b",
                         r"\bTranscribe\b", r"\bTranslate\b", r"\bPolly\b", r"\bAmazon Lex\b",
                         r"\bBedrock\b", r"\bmachine learning\b"],
}

AZURE_TOPICS: dict[str, list[str]] = {
    "Compute": [r"\bvirtual machines?\b", r"\bVMs?\b", r"\bApp Service\b", r"\bAzure Functions?\b",
                r"\bscale sets?\b", r"\bweb apps?\b"],
    "Containers": [r"(?-i)\bAKS\b", r"\bKubernetes\b", r"\bcontainers?\b", r"\bDocker\b", r"(?-i)\bACR\b",
                   r"\bContainer Registry\b", r"\bHelm\b"],
    "Storage": [r"\bstorage accounts?\b", r"\bBlob\b", r"\bAzure Files\b", r"\bmanaged disks?\b"],
    "Databases": [r"\bSQL Database\b", r"\bCosmos DB\b", r"\bdatabases?\b", r"\bSQL Server\b"],
    "Networking": [r"\bvirtual networks?\b", r"(?-i)\bVNets?\b", r"\bsubnets?\b", r"(?-i)\bNSGs?\b",
                   r"\bload balancer\b", r"\bApplication Gateway\b", r"\bFront Door\b", r"(?-i)\bVPN\b",
                   r"\bExpressRoute\b", r"(?-i)\bDNS\b"],
    "Identity & Security": [r"\bEntra\b", r"\bAzure AD\b", r"\bActive Directory\b", r"\bKey Vault\b",
                            r"\bmanaged identit", r"\bservice principals?\b", r"(?-i)\bRBAC\b",
                            r"\bDefender\b", r"\bconditional access\b", r"\bsecrets?\b"],
    "Monitoring": [r"\bAzure Monitor\b", r"\bApplication Insights\b", r"\bLog Analytics\b", r"(?-i)\bKQL\b",
                   r"\balerts?\b", r"\btelemetry\b"],
    "Governance": [r"\bAzure Policy\b", r"\bresource groups?\b", r"\bmanagement groups?\b", r"\bBlueprints?\b",
                   r"\btags?\b", r"\blocks?\b"],
}

AZ400_TOPICS: dict[str, list[str]] = {
    "Azure Pipelines": [r"\bAzure Pipelines?\b", r"\bpipelines?\b", r"\bYAML\b", r"\bbuild agents?\b",
                        r"\bagent pools?\b", r"\bself-hosted agents?\b", r"\brelease pipelines?\b",
                        r"\bstages?\b", r"\bvariable groups?\b"],
    "GitHub": [r"\bGitHub\b", r"\bGitHub Actions\b", r"\bworkflows?\b", r"\bCodespaces\b"],
    "Source Control": [r"\bGit\b", r"\bbranch", r"\bpull requests?\b", r"\brepositor", r"\bmerge\b",
                       r"\bcommits?\b", r"\bTFVC\b", r"\bGit LFS\b", r"\brebase\b", r"\bScalar\b"],
    "Boards & Collaboration": [r"\bAzure Boards\b", r"\bwork items?\b", r"\bdashboards?\b", r"\bwiki\b",
                               r"\bMicrosoft Teams\b", r"\bSlack\b", r"\bbacklog\b", r"\bKanban\b",
                               r"\bsprints?\b"],
    "Packages & Artifacts": [r"\bAzure Artifacts\b", r"\bfeeds?\b", r"\bNuGet\b", r"\bnpm\b", r"\bMaven\b",
                             r"\bpackages?\b", r"\bupstream sources?\b", r"\bsemantic version"],
    "Infrastructure as Code": [r"(?-i)\bARM\b", r"\bBicep\b", r"\bTerraform\b", r"\bAnsible\b", r"\bChef\b",
                               r"\bPuppet\b", r"\bDesired State Configuration\b", r"(?-i)\bDSC\b",
                               r"\bResource Manager templates?\b"],
    "Containers & Kubernetes": [r"(?-i)\bAKS\b", r"\bKubernetes\b", r"\bcontainers?\b", r"\bDocker",
                                r"\bHelm\b", r"\bContainer Registry\b"],
    "Testing & Quality": [r"\bunit tests?\b", r"\btests?\b", r"\bcode coverage\b", r"\bSonarQube\b",
                          r"\bSonarCloud\b", r"\btechnical debt\b", r"\bcode quality\b", r"\bload test"],
    "Security & Compliance": [r"\bKey Vault\b", r"\bsecrets?\b", r"\bservice connections?\b",
                              r"\bmanaged identit", r"\bvulnerabilit", r"\bDefender\b", r"\bCodeQL\b",
                              r"\bAdvanced Security\b", r"\bDependabot\b", r"\blicen[cs]e", r"\bWhiteSource\b",
                              r"\bMend\b", r"\bcompliance\b"],
    "Monitoring & Feedback": [r"\bApplication Insights\b", r"\bAzure Monitor\b", r"\bLog Analytics\b",
                              r"(?-i)\bKQL\b", r"\btelemetry\b", r"\balerts?\b", r"\bmonitor"],
    "Deployment Strategies": [r"\bdeployment slots?\b", r"\bblue[- /]green\b", r"\bcanary\b",
                              r"\bfeature flags?\b", r"\bApp Configuration\b", r"\bring", r"\brolling\b",
                              r"\bgates?\b", r"\bapprovals?\b"],
}


# ─────────────────────────────────────────────
#  DOMAIN PROFILES
# ─────────────────────────────────────────────

SAA_C03_DOMAINS: list[tuple[str, list[Rule]]] = [
    ("D1 · Secure Architectures", [
        (r"\bsecur(e|ely|ity)\b", 2), (r"\bencrypt", 3), (r"(?-i)\bKMS\b", 2), (r"\bIAM\b", 1),
        (r"\bpermissions?\b", 2), (r"\bleast[- ]privilege\b", 3), (r"\bcomplian", 2),
        (r"\bcredentials?\b", 2), (r"\bsecrets?\b", 2), (r"\bunauthori[sz]ed\b", 3),
        (r"\baudit", 2), (r"\bsensitive\b", 2), (r"(?-i)\bPII\b", 2), (r"\bprotect", 2),
        (r"\b(WAF|Shield|GuardDuty|Macie|Cognito)\b", 2), (r"\bprivate(ly)?\b", 1),
        (r"\bpublic internet\b", 1), (r"\bSQL injection\b", 3), (r"\b(DDoS|attacks?)\b", 3),
        (r"\baccess\b", 1), (r"\bauthenticat", 2), (r"\bauthori[sz]", 2), (r"\bregulat", 2),
    ]),
    ("D2 · Resilient Architectures", [
        (r"\bhighly available\b", 3), (r"\bhigh availability\b", 3), (r"\bavailab", 1),
        (r"\bfault[- ]toleran", 3), (r"\bresilien", 3), (r"\bdisaster recovery\b", 3),
        (r"(?-i)\b(RPO|RTO)\b", 3), (r"\bfailover\b", 2), (r"\bMulti-AZ\b", 2), (r"\bbackups?\b", 1),
        (r"\bdecoupl", 3), (r"\bloosely coupled\b", 3), (r"\bdurab", 2), (r"\bsingle point of failure\b", 3),
        (r"\boutages?\b", 2), (r"\brecover", 2), (r"\breplicat", 1), (r"\bdata loss\b", 2),
        (r"\breliab", 2), (r"\bmessages?\b", 1), (r"\bmultiple Availability Zones\b", 2),
    ]),
    ("D3 · High-Performing Architectures", [
        (r"\bperforman", 3), (r"\blatency\b", 3), (r"\bthroughput\b", 2), (r"(?-i)\bIOPS\b", 3),
        (r"\bscal(e|able|ability|ing)\b", 1), (r"\bcach", 2), (r"\bfast(er|est)?\b", 2),
        (r"\bquickly\b", 1), (r"\breal[- ]time\b", 2), (r"\bglobal(ly)?\b", 1), (r"\bspeed\b", 2),
        (r"\bread replicas?\b", 2), (r"\bcompute-intensive\b", 2), (r"\bhigh-performance\b", 3),
        (r"\bspikes?\b", 1), (r"\bunpredictable\b", 1), (r"\bingest", 1), (r"\banalytic", 1),
    ]),
    ("D4 · Cost-Optimized Architectures", [
        (r"\bcost", 3), (r"\bcheap", 3), (r"\bexpens", 3), (r"\bpric", 2), (r"\bbudget", 2),
        (r"\bReserved Instances?\b", 2), (r"\bSavings Plans?\b", 2), (r"\bSpot\b", 2),
        (r"\bIntelligent-Tiering\b", 2), (r"\blifecycle\b", 1), (r"\bbilling\b", 2),
        (r"\bspend", 2), (r"\bminimi[sz]e (the )?(cost|spend)", 3),
    ]),
]

CLF_C02_DOMAINS: list[tuple[str, list[Rule]]] = [
    ("D1 · Cloud Concepts", [
        (r"\bbenefits?\b", 2), (r"\badvantages?\b", 2), (r"\bWell-Architected\b", 3), (r"\bpillar", 3),
        (r"\bCloud Adoption Framework\b", 3), (r"(?-i)\bCAF\b", 3), (r"\beconom(y|ies) of scale\b", 3),
        (r"\bagility\b", 2), (r"\belasticity\b", 2), (r"\bdesign principles?\b", 3),
        (r"\bmigration strateg", 3), (r"\b(rehost|replatform|refactor|repurchase|retire|retain)\b", 2),
        (r"\bcapital expense", 2), (r"\bvariable expense", 2), (r"\bglobal(ly)?\b", 1),
    ]),
    ("D2 · Security and Compliance", [
        (r"\bshared responsibility\b", 4), (r"\bsecur", 2), (r"\bcomplian", 3), (r"\bIAM\b", 2),
        (r"\bencrypt", 2), (r"\bAWS Artifact\b", 3), (r"\b(GuardDuty|Inspector|Macie|Shield|WAF|Security Hub|Detective)\b", 2),
        (r"\bMFA\b", 2), (r"\broot user\b", 3), (r"\bpermissions?\b", 2), (r"\bcredentials?\b", 2),
        (r"\baudit", 2), (r"\bCloudTrail\b", 1), (r"\bpassword", 2), (r"\bDDoS\b", 2),
    ]),
    ("D3 · Cloud Technology and Services", [
        (r"\bRegions?\b", 1), (r"\bAvailability Zones?\b", 1), (r"\bedge locations?\b", 2),
        (r"\bdeploy", 1), (r"\bservice\b", 1), (r"\bdatabase", 1), (r"\bstorage\b", 1),
        (r"\bcompute\b", 1), (r"\bnetwork", 1),
    ]),
    ("D4 · Billing, Pricing, and Support", [
        (r"\bbill", 3), (r"\bpric", 3), (r"\bcost", 2), (r"\bSupport plans?\b", 3), (r"\bBusiness Support\b", 3),
        (r"\bEnterprise (On-Ramp|Support)\b", 3), (r"\bTechnical Account Manager\b", 3), (r"(?-i)\bTAM\b", 3),
        (r"\bBudgets\b", 3), (r"\bCost Explorer\b", 3), (r"\bconsolidated billing\b", 3),
        (r"\bSavings Plans?\b", 2), (r"\bReserved Instances?\b", 2), (r"\bMarketplace\b", 2),
        (r"\bpay", 1), (r"\binvoice", 2), (r"\bfree tier\b", 2),
    ]),
]

AZ400_DOMAINS: list[tuple[str, list[Rule]]] = [
    ("D1 · Processes & Communications", [
        (r"\bwork items?\b", 3), (r"\bAzure Boards\b", 3), (r"\bdashboards?\b", 2), (r"\bwiki\b", 3),
        (r"\bMicrosoft Teams\b", 2), (r"\bSlack\b", 2), (r"\brelease notes\b", 3), (r"\bdocumentation\b", 2),
        (r"\bbacklog\b", 2), (r"\bsprints?\b", 2), (r"\bcycle time\b", 3), (r"\blead time\b", 3),
        (r"\bGitHub Projects\b", 3), (r"\btraceability\b", 3), (r"\bprocess\b", 1), (r"\bagile\b", 2),
    ]),
    ("D2 · Source Control Strategy", [
        (r"\bbranch", 3), (r"\bGit\b", 1), (r"\bpull requests?\b", 2), (r"\bmerge\b", 2), (r"\brepositor", 1),
        (r"\bcommits?\b", 2), (r"\bTFVC\b", 3), (r"\bGit LFS\b", 3), (r"\brebase\b", 3), (r"\bScalar\b", 3),
        (r"\bmonorepo\b", 3), (r"\bfork", 2), (r"\bsquash\b", 3), (r"\bcherry-pick\b", 3),
    ]),
    ("D3 · Build & Release Pipelines", [
        (r"\bpipelines?\b", 2), (r"\bbuild\b", 2), (r"\breleases?\b", 1), (r"\bdeploy", 2), (r"\bYAML\b", 2),
        (r"\bagents?\b", 2), (r"\bartifacts?\b", 1), (r"\bpackages?\b", 1), (r"\bfeeds?\b", 2),
        (r"\bcontainers?\b", 1), (r"\bKubernetes\b", 1), (r"\bTerraform\b", 2), (r"\b(ARM|Bicep)\b", 2),
        (r"\btests?\b", 1), (r"\bdeployment slots?\b", 2), (r"\bblue[- /]green\b", 2), (r"\bcanary\b", 2),
        (r"\bfeature flags?\b", 2), (r"\bstages?\b", 1), (r"\bapprovals?\b", 1), (r"\bGitHub Actions\b", 2),
    ]),
    ("D4 · Security & Compliance Plan", [
        (r"\bKey Vault\b", 3), (r"\bsecrets?\b", 3), (r"\bservice connections?\b", 2), (r"\bmanaged identit", 3),
        (r"\bvulnerabilit", 3), (r"\bDefender\b", 3), (r"\bCodeQL\b", 3), (r"\bAdvanced Security\b", 3),
        (r"\bDependabot\b", 3), (r"\blicen[cs]e", 3), (r"\bcomplian", 2), (r"\bsecur", 2),
        (r"\bpermissions?\b", 1), (r"\bcredentials?\b", 2), (r"\bopen[- ]source\b", 2),
    ]),
    ("D5 · Instrumentation Strategy", [
        (r"\bApplication Insights\b", 3), (r"\bAzure Monitor\b", 3), (r"\bLog Analytics\b", 3),
        (r"(?-i)\bKQL\b", 3), (r"\btelemetry\b", 3), (r"\balerts?\b", 2), (r"\bmonitor", 2),
        (r"\blogs?\b", 1), (r"\bmetrics?\b", 1), (r"\bdiagnos", 2),
    ]),
]

# exam code → (topics, domains, fallback domain index or None)
PROFILES: dict[str, tuple[dict, list, int | None]] = {
    "saa-c03": (AWS_TOPICS, SAA_C03_DOMAINS, None),
    "clf-c02": (AWS_TOPICS, CLF_C02_DOMAINS, 2),
    "az-400": (AZ400_TOPICS, AZ400_DOMAINS, 2),
}

PROVIDER_TOPICS: dict[str, dict] = {
    "amazon": AWS_TOPICS,
    "microsoft": AZURE_TOPICS,
}

UNCLASSIFIED = "Unclassified"

_compiled: dict[int, object] = {}


def _compile_topics(topics: dict) -> list[tuple[str, list[re.Pattern]]]:
    key = id(topics)
    if key not in _compiled:
        _compiled[key] = [(name, [_rx(p) for p in pats]) for name, pats in topics.items()]
    return _compiled[key]


def _compile_domains(domains: list) -> list[tuple[str, list[tuple[re.Pattern, int]]]]:
    key = id(domains)
    if key not in _compiled:
        _compiled[key] = [(name, [(_rx(p), w) for p, w in rules]) for name, rules in domains]
    return _compiled[key]


def _question_sentence(stem: str) -> str:
    """The last sentence that asks the question (where requirements like
    'MOST cost-effective' or 'LEAST latency' usually live)."""
    sentences = re.split(r"(?<=[.?!])\s+", stem.strip())
    for s in reversed(sentences):
        if "?" in s:
            return s
    return sentences[-1] if sentences else ""


def detect_exam_code(questions: list[dict], hint: str | None = None) -> str:
    if hint:
        return hint.lower()
    for q in questions[:5]:
        m = re.search(r"exam\s+([a-z0-9]+-[a-z0-9]+)", q.get("title", ""), re.IGNORECASE)
        if m:
            return m.group(1).lower()
    return ""


def detect_provider(questions: list[dict], hint: str | None = None) -> str:
    if hint:
        return hint.lower()
    for q in questions[:5]:
        m = re.search(r"/discussions/([a-z0-9-]+)/", q.get("question_link", ""))
        if m:
            return m.group(1)
    return ""


def answer_letters(answer: str) -> list[str]:
    """'A, C' / 'AC' / 'A C' → ['A', 'C']. Returns [] for non-letter answers."""
    s = (answer or "").strip().upper()
    if not s or not re.fullmatch(r"[A-H](?:[\s,]*[A-H])*", s):
        return []
    return sorted(set(re.findall(r"[A-H]", s)))


def classify(q: dict, exam_code: str, provider: str) -> dict:
    """Set q['topic_tags'] (list) and q['domain'] (str or '')."""
    topics_map, domains, fallback = PROFILES.get(
        exam_code, (PROVIDER_TOPICS.get(provider, {}), [], None)
    )

    stem = q.get("content", "") or ""
    correct = set(answer_letters(q.get("voted_answer") or "") or answer_letters(q.get("answer") or ""))
    correct_text = " ".join(
        c.get("text", "") for c in q.get("choices", []) if c.get("letter") in correct
    )

    # ── Topics: stem + correct choices ──
    tag_text = stem + "\n" + correct_text
    tags = [name for name, pats in _compile_topics(topics_map) if any(p.search(tag_text) for p in pats)]
    q["topic_tags"] = tags or (["General"] if topics_map else [])

    # ── Domain: best score over stem, question sentence counted again ──
    q["domain"] = ""
    if domains:
        ask = _question_sentence(stem)
        best, best_score = None, 0
        for name, rules in _compile_domains(domains):
            score = 0
            for rx, w in rules:
                if rx.search(stem):
                    score += w
                if rx.search(ask):
                    score += w * 2
            if score > best_score:
                best, best_score = name, score
        if best is None and correct_text:
            # No signal in the stem: let the correct answer's wording decide
            for name, rules in _compile_domains(domains):
                score = sum(w for rx, w in rules if rx.search(correct_text))
                if score > best_score:
                    best, best_score = name, score
        if best is None and fallback is not None:
            best = domains[fallback][0]
        q["domain"] = best or UNCLASSIFIED
    return q
