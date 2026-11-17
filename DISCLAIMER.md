# Haftungsausschluss und Zweckbestimmung

*English version below.*

**Der Gutachter** ist ein **Forschungsprototyp (Proof of Concept)** und ein
**nicht-kommerzielles Open-Source-Projekt**. Die Software wird unentgeltlich und
ohne jede Gewährleistung zur Verfügung gestellt. Wer sie verwendet, tut dies auf
eigene Verantwortung.

## 1. Kein Medizinprodukt

Die Software ist **kein Medizinprodukt** im Sinne der Verordnung (EU) 2017/745 (MDR)
oder des schweizerischen Heilmittelrechts. Sie ist nicht dazu bestimmt, Krankheiten
oder Verletzungen zu diagnostizieren, zu verhüten, zu überwachen, vorherzusagen, zu
behandeln oder zu lindern. Sie trägt keine CE-Kennzeichnung und wurde **nicht
klinisch validiert**.

## 2. Zweckbestimmung

Ein Hilfsmittel für **qualifizierte medizinische Sachverständige**, um umfangreiche
Akten für Gutachten zu ordnen und durchzusehen: Texterkennung, Register der Dokumente,
chronologischer Aktenauszug mit Fundstellen, Hinweise auf mögliche Widersprüche,
Entwurfshilfe.

Alle Ergebnisse der Software sind **Entwürfe und Hinweise**. Die sachverständige
Person prüft **jede Angabe an der Originalquelle**, bevor sie diese verwendet.

## 3. Nicht bestimmungsgemässe Verwendung

Nicht bestimmt ist die Software insbesondere für:

- die Übernahme von Ergebnissen ohne Prüfung an der Originalakte;
- die Verwendung durch Personen ohne medizinische Fachqualifikation;
- automatisierte Entscheidungen über Kausalität, Arbeitsfähigkeit, Invalidität,
  Leistungen oder Ansprüche;
- Diagnose, Therapie oder sonstige Behandlung von Patientinnen und Patienten;
- den Einsatz als alleinige Grundlage eines Gutachtens oder einer Entscheidung.

## 4. Bekannte Grenzen

- **Texterkennung (OCR)** macht Fehler, besonders bei Handschrift, Faxen, schlechten
  Scans und Tabellen.
- **KI-Sprachmodelle** können Angaben **erfinden, auslassen, falsch datieren oder
  falsch zuordnen**. Die eingebauten Prüfungen (Zitat- und Datumsabgleich mit der
  Akte) verringern solche Fehler, **verhindern sie aber nicht**.
- Die **Widerspruchsprüfung** ist regelbasiert und unvollständig. Fehlende Hinweise
  bedeuten nicht, dass keine Widersprüche bestehen.
- Die Software kann nicht erkennen, ob **Dokumente oder Seiten in der Akte fehlen**.
- Einordnungen wie „Vorschaden“ oder „unfallkausal“ sind maschinelle Vorschläge,
  **keine medizinische oder rechtliche Beurteilung**.

## 5. Verantwortung

Die **alleinige fachliche und rechtliche Verantwortung** für den Inhalt eines
Gutachtens trägt die sachverständige Person, die es unterzeichnet. Die Software
ersetzt weder ärztliches Urteil noch die eigene Durchsicht der Akte.

## 6. Datenschutz

Die Software verarbeitet alle Falldaten **lokal** auf dem Gerät der Anwenderin oder
des Anwenders. Sie überträgt keine Falldaten an Dritte. Netzwerkzugriffe erfolgen
nur auf ausdrückliche Veranlassung, um Programmteile oder Sprachmodelle
herunterzuladen.

Wer die Software mit Gesundheitsdaten verwendet, ist **Verantwortliche oder
Verantwortlicher** im Sinne der DSGVO bzw. des schweizerischen DSG. Dazu gehören
insbesondere: Rechtsgrundlage der Verarbeitung, Verschlüsselung des Datenträgers
(z. B. BitLocker), Zugriffsschutz, Datensicherung und Löschung.

## 7. Keine Gewährleistung, Haftungsbeschränkung

Die Software wird **„wie besehen“ (as is)** bereitgestellt, ohne ausdrückliche oder
stillschweigende Gewährleistung, insbesondere ohne Gewähr für Richtigkeit,
Vollständigkeit, Eignung für einen bestimmten Zweck oder Fehlerfreiheit (siehe
Abschnitte 15 und 16 der Lizenz, AGPL-3.0).

**Soweit gesetzlich zulässig**, haften die Urheberinnen und Urheber sowie
Mitwirkende nicht für Schäden jeglicher Art, die aus der Verwendung oder der
Unmöglichkeit der Verwendung der Software entstehen, einschliesslich Schäden durch
fehlerhafte, unvollständige oder falsch zugeordnete Ergebnisse. Zwingende
gesetzliche Haftung, die nicht ausgeschlossen werden kann, bleibt unberührt.

## 8. Kein Support, keine Beratung

Es besteht **kein Anspruch** auf Support, Wartung, Fehlerbehebung, Aktualisierungen
oder Verfügbarkeit. Durch die Nutzung entsteht kein Vertragsverhältnis. Die Software
und ihre Dokumentation stellen **keine medizinische oder rechtliche Beratung** dar.

## 9. Drittkomponenten und Modelle

Die Software verwendet Komponenten Dritter unter deren eigenen Lizenzen (siehe
[NOTICE](NOTICE)). Sprachmodelle sind **nicht Teil dieses Projekts**. Sie werden
von deren Anbietern unter deren Lizenzen bezogen; für ihre Ausgaben gilt dieser
Haftungsausschluss ebenso.

## 10. Testdaten

Alle Namen, Personen, Institutionen, Daten und medizinischen Sachverhalte in Tests
und Beispielen sind **frei erfunden**. Ähnlichkeiten mit realen Personen oder
Einrichtungen sind zufällig.

---

# Disclaimer and Intended Purpose

**Der Gutachter** is a **research prototype (proof of concept)** and a
**non-commercial open-source project**. It is provided free of charge and without
any warranty. Use is at your own risk.

1. **Not a medical device.** It is not a medical device under Regulation (EU)
   2017/745 (MDR) or Swiss law. It is not intended for the diagnosis, prevention,
   monitoring, prediction, prognosis, treatment or alleviation of any disease or
   injury. It is not CE marked and **has not been clinically validated**.
2. **Intended purpose.** An aid for **qualified medical experts** to organise and
   review large case files for expert opinions: OCR, a document register, a
   chronological file summary with source citations, hints on possible
   contradictions, and drafting support. All outputs are **drafts and hints**. The
   expert verifies **every statement against the original source** before using it.
3. **Not intended for** use without that verification, use by non-qualified persons,
   automated decisions on causality, work capacity, disability, benefits or claims,
   diagnosis or treatment of patients, or as the sole basis of an expert opinion or
   decision.
4. **Known limitations.**
   - OCR makes errors (handwriting, faxes, poor scans).
   - AI language models can **invent, omit, misdate or misattribute** information.
     The built-in verification (quote and date matching against the file) reduces
     but **does not prevent** such errors.
   - The contradiction checks are rule-based and incomplete.
   - The software cannot detect missing documents or pages.
   - Labels such as "pre-existing condition" or "accident-related" are machine
     suggestions, **not a medical or legal assessment**.
5. **Responsibility.** **Sole professional and legal responsibility** for an expert
   opinion lies with the expert who signs it.
6. **Data protection.** All case data is processed **locally**, and no case data is
   transmitted. Network access happens only when explicitly requested, to download
   program parts or models. Users processing health data are **controllers** under
   the GDPR / Swiss FADP. They are responsible for the lawful basis, disk encryption,
   access control, backup and deletion.
7. **No warranty, limitation of liability.** Provided **"as is"**, without warranty
   of any kind (see sections 15 and 16 of the AGPL-3.0). **To the extent permitted
   by law**, the authors and contributors are not liable for any damages arising from
   the use of, or inability to use, the software, including damages caused by
   incorrect, incomplete or misattributed results. Mandatory statutory liability that
   cannot be excluded remains unaffected.
8. **No support, no advice.** There is no entitlement to support, maintenance,
   fixes, updates or availability. No contractual relationship arises from use.
   Nothing here constitutes medical or legal advice.
9. **Third-party components and models** are subject to their own licences (see
   [NOTICE](NOTICE)). Language models are **not part of this project**, and this
   disclaimer applies to their outputs as well.
10. **Test data** is entirely **fictitious**. Any resemblance to real persons or
    institutions is coincidental.
