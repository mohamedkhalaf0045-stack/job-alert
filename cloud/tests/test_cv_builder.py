"""Tests for cloud/cv_builder.py tailoring rules (no network, no browser)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv_builder as cb  # noqa: E402

MASTER = {
    "name": "Sam Example",
    "headline": "IT Systems Administrator | Microsoft 365",
    "contact": ["Abu Dhabi, UAE", "+971 50 000 0000"],
    "summary": "Admin with 8+ years supporting 500+ users at 99.9% uptime.",
    "skills": [{"category": "Cloud", "items": ["M365", "Intune", "Entra ID"]},
               {"category": "Network", "items": ["FortiGate", "VLAN"]}],
    "experience": [{"title": "Admin", "company": "A", "dates": "2022 – 2026",
                    "bullets": ["did AD", "did Intune", "did backups"]}],
    "certifications": ["AZ-900", "CCNA"],
}


def test_reorders_without_dropping_or_adding():
    plan = {"skill_order": [1, 7, "x", 1], "skill_items": {"0": [2, 0]},
            "bullet_order": {"0": [1]}, "cert_order": [1]}
    cv = cb.apply_tailoring(MASTER, plan)
    assert [g["category"] for g in cv["skills"]] == ["Network", "Cloud"]
    assert cv["skills"][1]["items"] == ["Entra ID", "M365", "Intune"]
    assert cv["experience"][0]["bullets"] == ["did Intune", "did AD", "did backups"]
    assert cv["certifications"] == ["CCNA", "AZ-900"]
    assert MASTER["skills"][0]["items"] == ["M365", "Intune", "Entra ID"]  # master untouched


def test_rejects_invented_numbers_in_summary_and_headline():
    ok = cb.apply_tailoring(MASTER, {"summary": "Intune-focused admin, 8+ years, 500+ users."})
    assert ok["summary"].startswith("Intune-focused")
    bad = cb.apply_tailoring(MASTER, {"summary": "Admin with 12 years and 2000 users.",
                                      "headline": "Senior Admin | 15 years"})
    assert bad["summary"] == MASTER["summary"]
    assert bad["headline"] == MASTER["headline"]


def test_empty_plan_keeps_master():
    cv = cb.apply_tailoring(MASTER, {})
    assert cv["summary"] == MASTER["summary"] and cv["skills"] == MASTER["skills"]


def test_tailor_without_key_returns_master():
    cv, tailored = cb.tailor(MASTER, {"job_title": "x"}, "desc", "")
    assert not tailored and cv == MASTER


def test_render_html_escapes_and_has_sections():
    cv = dict(MASTER, summary="R&D <b>")
    out = cb.render_html(cv)
    assert "R&amp;D &lt;b&gt;" in out
    for section in ["Professional Summary", "Core Technical Skills", "Professional Experience"]:
        assert section in out


def test_file_name():
    assert cb.file_name(MASTER, {"company": "YAS Projects LLC"}) == "Sam_Example_CV_YAS_Projects_LLC.pdf"
