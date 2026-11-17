# SPDX-License-Identifier: AGPL-3.0-or-later
from gutachten.analysis.style_check import check_report, check_section


def kinds(h):
    return sorted({x["kind"] for x in h})


def test_legal_terms_flagged():
    h = check_section("beurteilung", "Die adäquate Kausalität ist gegeben; Invalidität 40 %.", "")
    assert {x["text"] for x in h} >= {"Adäquanz / adäquate Kausalität", "Invalidität"}
    assert check_section("beurteilung", "Die Arbeitsfähigkeit beträgt 50 %.", "") == []


def test_weak_causality_wording():
    h = check_section("beurteilung", "Ein Zusammenhang mit dem Unfall ist möglich.", "")
    assert kinds(h) == ["beweismass"]
    ok = "Der Zusammenhang ist möglich, aber nicht überwiegend wahrscheinlich."
    assert check_section("beurteilung", ok, "") == []
    assert check_section("beurteilung", "Eine Besserung ist möglich.", "") == []


def test_abbreviations_explained_once_are_fine():
    secs = [{"section_key": "aktenauszug", "content_md": "Ruptur des vorderen Kreuzbandes (VKB)."},
            {"section_key": "beurteilung", "content_md": "VKB-Plastik stabil, ACG reizlos."}]
    h = check_report(secs)["beurteilung"]
    assert [x["text"] for x in h] == ["ACG"]  # VKB explained elsewhere, ACG not
    assert check_report(secs)["aktenauszug"] == []  # factual sections not checked


def test_no_sentence_split_after_abbreviations():
    from gutachten.analysis.style_check import _sentences
    t = "Laut Bericht (d. A.) ist z. B. die Beweglichkeit bzw. Kraft gemindert. Zweiter Satz."
    assert _sentences(t) == [
        "Laut Bericht (d. A.) ist z. B. die Beweglichkeit bzw. Kraft gemindert.", "Zweiter Satz."]
