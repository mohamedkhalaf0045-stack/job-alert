"""Tests for cloud/apply_answers.py (run: python -m pytest cloud/tests)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import apply_answers as aa  # noqa: E402

ANSWERS = {
    "personal": {"full_name": "Sam Example", "email": "sam@example.com",
                 "phone": "+971500000000", "city": "Abu Dhabi"},
    "experience": {"years": 4, "current_title": "IT Support Engineer", "skills": "AD, M365"},
    "screening": {"authorized_to_work": "Yes", "requires_sponsorship": "No",
                  "notice_period": "1 month", "expected_salary": "AED 9,000"},
    "open_text": {"why_interested": "I like the role."},
    "bank": {"visa_status": "Employment visa", "relocate": "Yes",
             "english_level": "Professional", "degree": "Bachelor's",
             "current_salary": ""},
    "custom": [{"q": "Do you have experience with Microsoft Intune?", "a": "Yes"},
               {"q": "", "a": "ignored"}],
}
BANK = aa.build_bank(ANSWERS)
CUSTOM = aa.custom_pairs(ANSWERS)


def ans(question, kind="text", options=None):
    return aa.answer_for(question, kind, options or [], BANK, CUSTOM)


def test_apply_screen_values_win_over_saved_bank():
    bank = aa.build_bank({"screening": {"notice_period": "Immediately"},
                          "bank": {"notice_period": "1 month", "nationality": "Egyptian"}})
    assert bank["notice_period"] == "Immediately" and bank["nationality"] == "Egyptian"


def test_build_bank_drops_empty_and_splits_name():
    assert BANK["first_name"] == "Sam" and BANK["last_name"] == "Example"
    assert "current_salary" not in BANK
    assert BANK["years"] == "4"
    assert CUSTOM == [("Do you have experience with Microsoft Intune?", "Yes")]


def test_rules_for_common_questions():
    assert ans("Mobile phone number*") == ("+971500000000", "rule")
    assert ans("What is your notice period?") == ("1 month", "rule")
    assert ans("What is your expected monthly salary (AED)?", "number") == ("9000", "rule")
    assert ans("How many years of work experience do you have with Active Directory?",
               "number") == ("4", "rule")
    assert ans("City") == ("Abu Dhabi", "rule")
    assert ans("First name") == ("Sam", "rule")


def test_choice_fields_pick_listed_option():
    assert ans("Will you now or in the future require visa sponsorship?", "radio",
               ["Yes", "No"]) == ("No", "rule")
    assert ans("Are you legally authorized to work in the UAE?", "radio",
               ["Yes", "No"]) == ("Yes", "rule")
    assert ans("Are you willing to relocate?", "select",
               ["Select an option", "Yes", "No"]) == ("Yes", "rule")
    assert ans("What is your level of proficiency in English?", "select",
               ["None", "Conversational", "Professional", "Native or bilingual"]) == (
        "Professional", "rule")


def test_custom_answer_wins_and_matches_near_identical_wording():
    assert ans("Do you have experience with Microsoft Intune?", "radio",
               ["Yes", "No"]) == ("Yes", "custom")
    assert ans("Do you have experience with Microsoft Intune ?*", "radio",
               ["Yes", "No"]) == ("Yes", "custom")


def test_unknown_question_returns_none():
    assert ans("Do you hold a valid CCNP certificate?", "radio", ["Yes", "No"]) == (None, "")
    # rule matches but the bank has no value
    assert ans("What is your current salary?") == (None, "")
    # rule value cannot be mapped to the options → not guessed
    assert ans("Are you willing to relocate?", "select", ["Dubai", "Riyadh"]) == (None, "")


def test_choose_option_ranges():
    opts = ["0-1 years", "2-3 years", "4-6 years", "7+ years"]
    assert aa.choose_option("4", opts) == "4-6 years"
    assert aa.choose_option("9", opts) == "7+ years"
    assert aa.choose_option("yes", ["Yes, I am", "No"]) == "Yes, I am"
    assert aa.choose_option("maybe", ["Yes", "No"]) is None


def test_parse_llm_reply_validates():
    assert aa.parse_llm_reply('{"answer": "No", "confident": true}', "radio", ["Yes", "No"]) == "No"
    assert aa.parse_llm_reply('{"answer": "Maybe", "confident": true}', "radio", ["Yes", "No"]) is None
    assert aa.parse_llm_reply('{"answer": "Yes", "confident": false}', "radio", ["Yes", "No"]) is None
    assert aa.parse_llm_reply('Sure! {"answer": "about 5 years", "confident": true}',
                              "number", []) == "5"
    assert aa.parse_llm_reply("not json", "text", []) is None


def test_ask_groq_without_key_is_none():
    assert aa.ask_groq("Q?", "text", [], "profile", {}, "") is None
