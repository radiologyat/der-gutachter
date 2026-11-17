# Der Gutachter – Installation (Windows 11)

*Für Anwenderinnen und Anwender. Dauer: ca. 15 Minuten plus Download der Modelle.*

> **Forschungsprototyp, kein Medizinprodukt.** Alle Ergebnisse sind Entwürfe, die Sie
> an der Originalakte prüfen. Bitte vorab [DISCLAIMER.md](../DISCLAIMER.md) lesen.

## Was Sie brauchen

- Windows 11, 64 Bit, mindestens 16 GB Arbeitsspeicher (32 GB empfohlen)
- Eine NVIDIA-Grafikkarte wird empfohlen (z. B. RTX 5070, 8 GB), ist aber nicht nötig
- Ca. 15 GB freier Speicherplatz
- Empfohlen: BitLocker-Verschlüsselung des Laufwerks (Einstellungen → Datenschutz und
  Sicherheit → Geräteverschlüsselung)

## 1. Installieren

1. `DerGutachter-Setup-….exe` **vom USB-Stick** starten. Vom USB-Stick kopierte Dateien
   startet Windows in der Regel ohne Warnung.
2. Falls Windows doch warnt („Der Computer wurde durch Windows geschützt“ oder
   „Unbekannter Herausgeber“): **Weitere Informationen** → **Trotzdem ausführen**.
   Die Warnung erscheint, weil das Projekt kein kostenpflichtiges Zertifikat verwendet —
   sie sagt nichts über Schadsoftware aus.
3. Haftungsausschluss lesen → **Ich akzeptiere** → Installieren.
   Keine Administratorrechte nötig.
4. „Der Gutachter starten“ angehakt lassen → Fertigstellen.

> **Ohne Installation:** Statt des Installers kann auch `DerGutachter-Portable.zip`
> entpackt und `DerGutachter.exe` direkt gestartet werden, etwa auf Rechnern, auf
> denen nichts installiert werden darf.
> Empfehlung: die ZIP **vor dem Entpacken** freigeben (Rechtsklick → Eigenschaften →
> „Zulassen“ anhaken). Ab Version 0.9.2 erledigt die App das für ihre eigenen Dateien
> beim Start selbst; in 0.9.1 brach das Fenster sonst mit „Failed to resolve
> Python.Runtime.Loader.Initialize“ ab.

> **Smart App Control:** Blockiert Windows den Start („Diese App wurde blockiert“), ist
> die Smart App Control aktiv (Windows-Sicherheit → App- & Browsersteuerung). Bitte
> **nicht** selbst ausschalten – wenden Sie sich an Ihre IT oder den Herausgeber.

## 2. Herausgeber anzeigen lassen (optional)

Nur nötig, wenn Windows statt „Unbekannter Herausgeber“ den Namen „Der Gutachter
(selbstsigniert)“ anzeigen soll und Sie bei Updates sehen möchten, dass sie vom
selben Herausgeber stammen. Benötigt einmalig Administratorrechte; häufig übernimmt das
die IT.

1. Im Programmordner (oder auf dem USB-Stick) den Ordner `Zertifikat` öffnen.
2. `Zertifikat-vertrauen.ps1` → Rechtsklick → **Mit PowerShell ausführen**.
3. Den angezeigten **SHA-256-Fingerabdruck** mit diesem vergleichen und mit `j`
   bestätigen:

   `80:33:B1:CB:3B:5C:C5:8B:E9:FC:FD:14:28:78:5E:67:02:6D:EC:CD:6D:EF:A4:83:06:3A:EF:C5:DD:6B:82:D8`

**Echtheit des Downloads prüfen (optional):** Neben dem Installer liegt
`SHA256SUMS.txt`. In PowerShell: `Get-FileHash DerGutachter-Setup-….exe` – der Wert
muss mit der Datei übereinstimmen.

## 3. Erster Start

1. Haftungsausschluss lesen, Häkchen setzen → **Weiter**.
2. Die **Einrichtung** öffnet sich automatisch. Sie zeigt Arbeitsspeicher, Grafikkarte und
   freien Speicher und wählt das Passende vor.
3. **Herunterladen** klicken (ca. 7,6 GB). Ein abgebrochener Download wird beim nächsten
   Mal fortgesetzt. *Ohne Internet:* Modelldateien vom USB-Stick mit **Aus Ordner
   importieren** übernehmen.
4. Danach **Zur Arbeitsliste**.

Dies ist die einzige Internetverbindung der Anwendung. Es werden keine Falldaten
übertragen.

## 4. Eine Akte bearbeiten

1. **Akte-Ordner öffnen …** → den Ordner mit den Unterlagen wählen. Ein kurzer Dialog
   fragt nach dem Land (Schweiz oder Österreich, wird gemerkt) und ob ein KI-Vorentwurf
   erstellt werden soll. Die Auftragsart (IV, Unfallversicherung, Haftpflicht/Gericht)
   wird aus dem Auftraggeber erkannt und ist in der Übersicht änderbar. Die Dateien
   werden nach Namen sortiert übernommen – der Gutachtenauftrag sollte zuerst kommen
   (z. B. `01_Auftrag.pdf`).
2. Die Auswertung läuft von selbst in dieser Reihenfolge:
   **Gutachtenauftrag** (Texterkennung der Auftragsseiten, Auftraggeber, Unfalldatum,
   Fristen, Beweisfragen) → **Texterkennung** aller übrigen Seiten → **Register** →
   **Extraktion** → **Aktenauszug** → **Prüfung** → **Entwurf** (optional KI-Vorentwurf).
3. Die **Aktivitätsleiste** oben zeigt jederzeit, was läuft: Schritt, Fortschritt,
   woran das Sprachmodell gerade arbeitet (und seit wann), Laufzeit, geschätzte
   Restzeit und den Verlauf. Eine einzelne Modellanfrage kann ohne Grafikkarte
   mehrere Minuten dauern; erst nach längerer Zeit ohne jede
   Rückmeldung erscheint eine Warnung.
4. Reiter **Hinweise** prüfen, im Reiter **Gutachten** jeden Abschnitt prüfen,
   ergänzen und **freigeben**, dann **Word exportieren**.

**Alles aktualisieren:** Ein Klick im Fall erkennt neue Seiten und Änderungen
(z. B. korrigierte Einträge, ergänzter Befund), rechnet nur das Betroffene neu und zeigt
danach unter „Es fehlt noch“, was offen ist. Eigene Texte und Freigaben bleiben erhalten.

**Mehrere Akten:** Ordner nacheinander öffnen. Die Auswertungen laufen
nacheinander (Anzeige „wartet“), weil sie dasselbe lokale Sprachmodell nutzen.

**Speichern und Fortsetzen:** Alles wird laufend gespeichert – Fälle, erkannte Seiten,
jede Modellantwort, Korrekturen. Die App kann jederzeit geschlossen werden. Wurde eine
Auswertung dabei unterbrochen, zeigen Arbeitsliste und Fall **„unterbrochen —
fortsetzen“**; beim Fortsetzen werden fertige Seiten und bereits erhaltene
Modellantworten übernommen, es geht ab der Unterbrechung weiter.

**Wie gut lief es?** Reiter **Protokoll** → **Diagnose**: Seiten mit verwertbarem Text,
Dokumente, gefundene und belegte Angaben (mit Gründen für Verworfenes),
Modellanfragen mit Dauer und Fehlern, und worauf das Sprachmodell läuft
(NVIDIA CUDA, Grafikkarte über Vulkan, oder nur Prozessor).

## Wo liegen meine Daten?

`%LOCALAPPDATA%\DerGutachter\data` (Fälle) und `…\models` (Modelle) – auch bei der
portablen Version. Bei der Deinstallation bleiben beide erhalten.

**Update von Version 0.9.8 oder älter:** Ab 0.9.9 arbeitet die App mit dem Sprachmodell
Gemma 4 12B. Nach dem Update zeigt die Einrichtung das Modell als fehlend an; bitte dort
herunterladen (ca. 7 GB). Bestehende Fälle bleiben erhalten, Auswertungen werden mit dem
neuen Modell neu berechnet. Der Ordner `…\models\gguf\qwen35-9b` des alten Modells
wird nicht mehr benötigt und kann gelöscht werden (ca. 5,7 GB).

## Probleme

**Grafikkarte / CUDA nicht erkannt:** Einrichtung → **Grafikkarte prüfen** zeigt, ob
`nvidia-smi` gefunden wurde, welche Grafikadapter Windows meldet und worauf das
Sprachmodell läuft. Auch ohne das CUDA-Paket rechnet eine NVIDIA-Karte über die
mitgelieferte Vulkan-Version; nur „nur Prozessor“ ist langsam. Ist die Karte erkannt,
aber der Treiber zu alt für CUDA 13.5, den NVIDIA-Treiber aktualisieren.


Protokolle: `%LOCALAPPDATA%\DerGutachter\data\logs\app.log` und `llama-server.log`.
Es gibt keinen Support-Anspruch (siehe Haftungsausschluss).
