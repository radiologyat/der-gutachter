# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from gutachten.dates import date_supported, find_dates, normalize_iso


@pytest.mark.parametrize("text,iso", [
    ("am 14.03.2021 vorgestellt", "2021-03-14"),
    ("Datum: 4.3.21", "2021-03-04"),
    ("14/03/2021", "2021-03-14"),
    ("2021-03-14", "2021-03-14"),
    ("Wien, 14. März 2021", "2021-03-14"),
    ("Wien, 3. Jänner 2022", "2022-01-03"),   # Austrian month name
    ("14. Maerz 2021", "2021-03-14"),
    ("seit März 2021", "2021-03"),
    ("Reha 03/2021", "2021-03"),
    ("1. Okt. 2023", "2023-10-01"),
])
def test_find_dates(text, iso):
    assert [f.iso for f in find_dates(text)] == [iso]


def test_invalid_and_ambiguous_dates_ignored():
    assert find_dates("31.02.2021") == []
    assert find_dates("Tel. 044 123 45 67, PLZ 8000") == []
    assert find_dates("Version 1.2.3") == []


def test_normalize_iso():
    assert normalize_iso("2021-03-14") == "2021-03-14"
    assert normalize_iso("2021-03") == "2021-03"
    assert normalize_iso("2021") == "2021"
    assert normalize_iso("14.03.2021") == "2021-03-14"
    assert normalize_iso("2021-02-30") is None
    assert normalize_iso("gestern") is None
    assert normalize_iso("") is None and normalize_iso(None) is None


def test_date_supported_respects_precision():
    text = "Arztbrief vom 14.03.2021. Beschwerden seit Januar 2020."
    assert date_supported("2021-03-14", text)
    assert date_supported("2021-03", text)       # month of a stated day
    assert date_supported("2020-01", text)
    assert date_supported("2020", text)
    assert not date_supported("2020-01-15", text)  # day would be invented
    assert not date_supported("2021-03-15", text)


def test_date_ranges_without_year_on_the_start():
    assert [f.iso for f in find_dates("Aufenthalt: 15.10.-18.10.2016")] == [
        "2016-10-15", "2016-10-18"]
    assert [f.iso for f in find_dates("Reha 15.-18.10.2016")] == ["2016-10-15", "2016-10-18"]
    assert [f.iso for f in find_dates("vom 08.01. – 02.02.2024")] == ["2024-01-08", "2024-02-02"]
    assert date_supported("2016-10-15", "Aufenthalt: 15.10.-18.10.2016")


def test_french_italian_dates():
    # Swiss files can be in German, French or Italian
    assert [f.iso for f in find_dates("Arrêt du 23 août 2023")] == ["2023-08-23"]
    assert [f.iso for f in find_dates("décision du 20 janvier 2023")] == ["2023-01-20"]
    assert [f.iso for f in find_dates("le 21 février 2023")] == ["2023-02-21"]
    assert [f.iso for f in find_dates("sentenza del 7 agosto 2008")] == ["2008-08-07"]
    assert [f.iso for f in find_dates("il 23 marzo 2023")] == ["2023-03-23"]
    assert [f.iso for f in find_dates("15 dicembre 2021")] == ["2021-12-15"]
    assert normalize_iso("23 août 2023") == "2023-08-23"
    assert date_supported("2023-08-23", "Arrêt du 23 août 2023")
    assert date_supported("2008-08-07", "sentenza del 7 agosto 2008")
    assert date_supported("2023-02-21", "à compter du 21 février 2023")
    assert not date_supported("2023-08-24", "Arrêt du 23 août 2023")
