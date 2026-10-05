# Report style

Every `ush-*` report follows these rules. A skill's `references/report-format.md`
says what its report contains; this file says how it is written. Where the two
differ, this file wins.

The report checker (`skills/ush-common/scripts/check_report.py`) checks the
numbers, every local/UTC pair of rule 1 and every „HH:MM UTC)” outside such a
pair, and the `Set-Location`, `--data-dir` and backtick continuation of
rule 9. It does not catch a
time written without its pair: rule 1 is still the writer's job, and so are
the other rules.

1. **Time.**
   - A JSON time with a zone is written in local time with its UTC time in
     brackets, to the minute: „2026-09-30 09:26 (07:26 UTC)”. Drop the seconds,
     never round. The checker verifies that the pair matches a time in the JSON,
     or that its text is quoted from a JSON string value (a message).
   - A time without a zone and a date without a time (for example `not_after`)
     are copied exactly as written.
   - Never a UTC time on its own, and never another date order.

   Good:

   ```markdown
   Przebieg zakończony 2026-09-30 09:26 (07:26 UTC).
   ```

   Bad:

   ```markdown
   Przebieg zakończony 2026-09-30 10:26 (07:26 UTC).
   ```

2. **Numbers.** The decimal separator of the report language (a comma in a
   Polish report), and „%” without a space („69,0%”). Copy the digits and the
   precision of the JSON; never round further. The numbers in the examples of
   every `report-format.md` are written for a Polish report.

   Good:

   ```markdown
   Wolne miejsce: 69,0%.
   ```

   Bad:

   ```markdown
   Wolne miejsce: 69 percent.
   ```

3. **Dash.** Only „—” with a space on each side, also in legends. A hyphen only
   inside a word, as a list marker and in code.

   Good:

   ```markdown
   - 🔧 do zmiany — blok gotowy do wklejenia
   ```

   Bad:

   ```markdown
   - 🔧 do zmiany - blok gotowy do wklejenia
   ```

4. **Recommendation layout.** One layout in every report. A Polish report uses
   the labels below; a report in another language uses the same layout with the
   labels translated. Each field is a list item of its own with the label in
   bold: `- **Waga:** wysoka`.

   | field | label | values |
   |---|---|---|
   | `weight` | Waga | wysoka, średnia, niska |
   | `kind` | Rodzaj | zmiana, obserwacja, serwis |
   | `risk` | Ryzyko | what can go wrong |
   | `evidence` | Dowód | the numbers and ids it rests on |
   | `permissions` | Uprawnienia | e.g. brak, administrator |
   | `rollback` | Cofnięcie | how to undo it |

   Good:

   ```markdown
   - **Waga:** średnia
   - **Rodzaj:** zmiana
   - **Ryzyko:** niskie — usługa wraca po ponownym uruchomieniu.
   - **Dowód:** g3 Invented-Disk (40).
   - **Uprawnienia:** administrator
   - **Cofnięcie:** blok przywracający poniżej.
   ```

   Bad:

   ```markdown
   **weight:** medium, **risk:** low - service comes back
   ```

5. **Plain language.** Describe what a field means in words. The field name goes
   only in brackets, at most once per section.

   Good:

   ```markdown
   Szyfrowanie dysku jest wyłączone (`protection_status`).
   ```

   Bad:

   ```markdown
   protection_status = 0
   ```

6. **Ids with names.**
   - Every item id comes with a short name after it: „g3 Invented-Disk”.
     A count goes in brackets after the name (rule 7).
   - No lists of bare ids. Every id of a list the checker requires
     (`required_lists` in `data/report-profile.json`) is still named, each with
     its short name.

   Good:

   ```markdown
   Najwięcej zdarzeń ma g3 Invented-Disk.
   ```

   Bad:

   ```markdown
   Najwięcej zdarzeń ma g3.
   ```

7. **Long lists.** The conclusion first, then the unusual entries in full. The
   rest of a required list follows in one compact line of `id name (count)`,
   never only a count.

   Good:

   ```markdown
   Wniosek: tylko g3 Invented-Disk (40) odbiega od normy.
   Pozostałe grupy: g29 Service Control Manager (2), g22 Kernel-Power (1), g7 Invented-Sync (1), g12 Invented-Update (1).
   ```

   Bad:

   ```markdown
   Grup jest 5; pozostałe pominięto.
   ```

8. **Blocks now.** A change the report finds acceptable gets its paste-ready
   block and its rollback in the report's recommendations section, never „on
   request in the next report”. A skill whose format hands changes to another
   skill (processes hands ending and disabling to `ush-inventory`) gives no block
   of its own; it names that skill and the entry's key.

   Good:

   ```markdown
   Blok do wklejenia i blok cofający są niżej, przy zaleceniu.
   ```

   Bad:

   ```markdown
   Blok podam w kolejnym raporcie, jeśli zechcesz.
   ```

9. **Script commands.** Every block that runs a skill script has a
   `Set-Location` line with the absolute project root, and, on the same line as
   the script, `--data-dir` with the absolute data directory. One command per
   line, no backtick continuation. The checker enforces the absolute
   `Set-Location` and `--data-dir`, and reports a skill script command
   continued with a backtick as an error of its own.

   Good:

   ````markdown
   ```powershell
   Set-Location "C:\proj"
   python -B skills/ush-events/scripts/events.py --data-dir "C:\dane\ush"
   ```
   ````

   Bad:

   ````markdown
   ```powershell
   Set-Location "C:\proj"
   python -B skills/ush-events/scripts/events.py
   ```
   ````

   Bad:

   ````markdown
   ```powershell
   Set-Location "C:\proj"
   python -B skills/ush-events/scripts/events.py `
     --data-dir "C:\dane\ush"
   ```
   ````

10. **One language.** No words from a language other than the report's (the
    language the user addressed the skill in).
    - Translate catalogue titles, `not_checked` items (`what` and `reason`) and
      labels.
    - A suffix in another language that a script added to a name is written as
      the name plus a note in the report's language.
    - Only ids and values quoted as data stay as they are, in backticks.

    Good:

    ```markdown
    Nie sprawdzono: dziennik zabezpieczeń — brak uprawnień administratora.
    ```

    Bad:

    ```markdown
    Nie sprawdzono: Security log — access denied.
    ```

11. **No filler.** No explanation of how a script works unless it changes the
    decision.

    Good:

    ```markdown
    Od poprzedniego przebiegu nic się nie zmieniło.
    ```

    Bad:

    ```markdown
    Skrypt porównał bieżący stan z plikiem stanu, odczytując każdą pozycję.
    ```

12. **Baseline age.** The „Pulpit” table row on changes gives the baseline time
    as in rule 1 and its age (`baseline.created_at`, `baseline.age_days`).

    Good:

    ```markdown
    | Zmiany | 3 od stanu z 2026-09-20 12:15 (10:15 UTC), 10 dni |
    ```

    Bad:

    ```markdown
    | Zmiany | 3 |
    ```

13. **Accounts.** Name an account by its role when the summary gives one, not
    by a name two accounts share.

    Good:

    ```markdown
    Konto administratora wbudowanego jest wyłączone.
    ```

    Bad:

    ```markdown
    Konto Invented jest wyłączone.
    ```

14. **No recommendations.** A report without recommendations says so in a fixed
    sentence: in a Polish report „Brak zaleceń w tym przebiegu.”, in another
    language its translation.

    Good:

    ```markdown
    Brak zaleceń w tym przebiegu.
    ```

    Bad:

    ```markdown
    Brak zaleceń (wszystko wygląda dobrze, ale warto sprawdzić później).
    ```
