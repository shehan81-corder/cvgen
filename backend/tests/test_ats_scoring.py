from app.services.ats_scoring import match_score


def test_cv_with_all_jd_keywords_scores_100():
    # A flat keyword list (no filler verbs) so every JD keyword is a real
    # requirement the CV either has or doesn't — filler words like "looking"
    # or "experienced" would themselves count as unmet keywords otherwise,
    # which is realistic for this heuristic but not what this test checks.
    jd = "Python, AWS, Docker, Kubernetes"
    cv = "I have hands-on experience with Python, AWS, Docker, and Kubernetes in production."
    assert match_score(jd, cv) == 100.0


def test_cv_with_no_jd_keywords_scores_zero():
    jd = "Python, AWS, Docker, Kubernetes"
    cv = "Passionate florist with a love of watercolor painting."
    assert match_score(jd, cv) == 0.0


def test_plural_and_verb_form_variants_still_match():
    jd = "We need someone managing teams and developing scalable systems."
    cv = "Managed a team and developed a scalable system last year."
    score = match_score(jd, cv)
    assert score > 50.0


def test_tailored_cv_scores_higher_than_original_when_more_keywords_present():
    jd = "Seeking a candidate skilled in Kubernetes, Terraform, and CI/CD pipelines."
    original_cv = "Backend engineer with general cloud experience."
    tailored_cv = (
        "Backend engineer with hands-on Kubernetes and Terraform experience, "
        "building CI/CD pipelines."
    )
    assert match_score(jd, tailored_cv) > match_score(jd, original_cv)


def test_keyword_in_fixed_style_text_still_counts():
    # Scoring runs on full text regardless of editable/fixed classification
    # (architecture.md §8) — a keyword sitting in a job title still counts.
    jd = "Kubernetes"
    job_title_line = "Kubernetes Platform Engineer, Acme Corp"
    assert match_score(jd, job_title_line) == 100.0
