"""Job Description parsing and extraction service."""

import re


# Common skill keywords to match against JDs
TECH_SKILLS = [
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "golang", "rust", "ruby", "php", "swift", "kotlin", "sql", "html", "css", "scss", "scala", "r",
    # Frontend
    "react", "vue", "vue.js", "vuejs", "angular", "next.js", "nextjs", "nuxt", "svelte", "tailwind", "tailwind css", "bootstrap", "jquery", "redux", "zustand",
    # Backend
    "fastapi", "django", "flask", "express", "express.js", "node.js", "nodejs", "spring", "spring boot", "rails", "ruby on rails", "laravel", "asp.net",
    # Databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch", "sqlite", "dynamodb", "cassandra", "neo4j", "mariadb", "firebase",
    # Cloud
    "aws", "amazon web services", "gcp", "google cloud", "azure", "microsoft azure", "heroku", "vercel", "netlify",
    # DevOps/Infra
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins", "github actions", "ci/cd", "nginx", "apache", "linux", "bash",
    # ML/AI
    "machine learning", "deep learning", "nlp", "natural language processing", "pytorch", "tensorflow", "scikit-learn", "keras",
    "pandas", "numpy", "opencv", "hugging face", "huggingface", "langchain", "openai", "llm", "large language model", "rag",
    "retrieval augmented generation", "transformers", "neural network", "computer vision",
    # Data
    "spark", "hadoop", "kafka", "airflow", "dbt", "snowflake", "bigquery", "tableau", "power bi",
    # Tools
    "git", "github", "gitlab", "bitbucket", "rest api", "rest", "graphql", "grpc", "websocket",
    "celery", "rabbitmq", "kafka", "microservices", "agile", "scrum", "jira", "confluence",
]

SENIORITY_KEYWORDS = {
    "intern": ["intern", "internship", "trainee"],
    "entry": ["entry level", "entry-level", "junior", "graduate", "0-2 years", "0-1 years", "fresher"],
    "mid": ["mid level", "mid-level", "2-5 years", "3-5 years", "3+ years", "2+ years"],
    "senior": ["senior", "sr.", "lead", "staff", "5+ years", "7+ years", "principal"],
    "director": ["director", "head of", "vp", "vice president", "c-level", "cto", "ceo"],
}


def parse_jd(raw_text: str) -> dict:
    """Parse a job description into structured fields."""
    text_lower = raw_text.lower()

    # Extract skills
    must_have_skills = []
    nice_to_have_skills = []

    # Look for "requirements" / "must have" vs "nice to have" / "preferred" sections
    requirements_section = ""
    preferred_section = ""

    req_match = re.search(
        r"(?:requirements|must[\s-]*have|required|qualifications)[\s:]*\n(.*?)(?:(?:nice[\s-]*to[\s-]*have|preferred|bonus|desired)[\s:]*\n|$)",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    if req_match:
        requirements_section = req_match.group(1).lower()

    pref_match = re.search(
        r"(?:nice[\s-]*to[\s-]*have|preferred|bonus|desired)[\s:]*\n(.*?)(?:(?:about|benefits|perks|who we|we offer|salary|compensation)[\s:]*\n|$)",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    if pref_match:
        preferred_section = pref_match.group(1).lower()

    # Match skills against the full text
    for skill in TECH_SKILLS:
        if skill in text_lower:
            # Determine if it's in requirements or preferred section
            in_requirements = skill in requirements_section if requirements_section else False
            in_preferred = skill in preferred_section if preferred_section else False

            if in_preferred and not in_requirements:
                nice_to_have_skills.append(skill)
            elif in_requirements or not (requirements_section or preferred_section):
                must_have_skills.append(skill)

    # Determine seniority
    seniority = "not specified"
    for level, keywords in SENIORITY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                seniority = level
                break
        if seniority != "not specified":
            break

    # Extract role title — first meaningful line or common patterns
    role = ""
    role_patterns = [
        re.compile(r"^(?:job title|position|role)[\s:]+(.+)$", re.IGNORECASE | re.MULTILINE),
    ]
    for pattern in role_patterns:
        m = pattern.search(raw_text)
        if m:
            role = m.group(1).strip()
            break

    if not role:
        # Use first line that looks like a title
        for line in raw_text.split("\n")[:5]:
            stripped = line.strip()
            if stripped and len(stripped) < 120 and not stripped.lower().startswith(("we ", "our ", "the ", "about", "looking")):
                role = stripped
                break

    # Extract responsibilities
    responsibilities = []
    resp_match = re.search(
        r"(?:responsibilities|what you(?:'ll| will) do|your role|duties)[\s:]*\n(.*?)(?:(?:requirements|qualifications|must[\s-]*have|benefits|perks|about)[\s:]|\Z)",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    if resp_match:
        resp_text = resp_match.group(1)
        for line in resp_text.split("\n"):
            stripped = line.strip().lstrip("•-*–→")
            if stripped and len(stripped) > 5:
                responsibilities.append(stripped)

    # Deduplicate skills
    must_have_skills = list(dict.fromkeys(must_have_skills))
    nice_to_have_skills = list(dict.fromkeys(nice_to_have_skills))

    return {
        "role": role,
        "must_have_skills": must_have_skills,
        "nice_to_have_skills": nice_to_have_skills,
        "responsibilities": responsibilities,
        "seniority": seniority,
    }


async def fetch_jd_from_url(url: str) -> str:
    """Fetch job description text from a URL."""
    import httpx
    from bs4 import BeautifulSoup

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 JobCopilot/1.0"})
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script/nav/footer
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return text
