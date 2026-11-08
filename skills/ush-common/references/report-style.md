# Report style

Every `ush-*` report follows these rules. A skill's `references/report-format.md`
says what its report contains; this file says how it is written. Where the two
differ, this file wins.

The report checker (`<plugin root>/skills/ush-common/scripts/check_report.py`) checks the
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
   - 🔧 do zmiany — blok podam po Twojej decyzji
   ```

   Bad:

   ```markdown
   - 🔧 do zmiany - blok podam po Twojej decyzji
   ```

4. **Recommendation layout.** One layout in every report, in two parts. A
   Polish report uses the labels below; a report in another language uses the
   same layout with the labels translated. Each field is a list item of its
   own with the label in bold: `- **Waga:** wysoka`.

   Part one is what the user reads first, in this order:

   | field | label | values |
   |---|---|---|
   | — | Problem | the problem in plain words and why it matters |
   | — | Co zrobić | what to do now: option A or B in words, or „nie da się dziś naprawić — obserwujemy” with what would change that |
   | `weight` | Waga | wysoka, średnia, niska |

   Part two, `Szczegóły`, stands lower in the same recommendation, as one
   item with the label in bold and the fields nested under it:

   | field | label | values |
   |---|---|---|
   | `kind` | Rodzaj | zmiana, obserwacja, serwis |
   | `risk` | Ryzyko | what can go wrong |
   | `evidence` | Dowód | the numbers and ids it rests on |
   | `permissions` | Uprawnienia | e.g. brak, administrator |
   | `rollback` | Cofnięcie | how to undo it |

   `Problem` and `Co zrobić` are written by the model from the evidence; they
   carry no number the evidence does not back. `Co zrobić` proposes a change
   in words and gives no block (rule 8). The chat answer gives part one only;
   the report keeps both parts.

   Good:

   ```markdown
   - **Problem:** usługa Invented-Sync zatrzymuje się przy starcie, więc pliki się nie synchronizują.
   - **Co zrobić:** A — ustaw opóźniony start usługi (ta umiejętność nie ma na to gotowego bloku, więc gdy zdecydujesz, opiszę krok słowami); B — zostaw tak i obserwuj w kolejnym przebiegu.
   - **Waga:** średnia
   - **Szczegóły:**
     - **Rodzaj:** zmiana
     - **Ryzyko:** niskie — usługa wraca po ponownym uruchomieniu.
     - **Dowód:** g7 Invented-Sync (1), g29 Service Control Manager (2).
     - **Uprawnienia:** administrator
     - **Cofnięcie:** przywrócenie startu automatycznego; krok cofający opiszę razem z krokiem zmiany.
   ```

   Bad:

   ```markdown
   - **Dowód:** g7 Invented-Sync (1), g29 Service Control Manager (2).
   - **Ryzyko:** niskie
   - **Co zrobić:** wklej blok poniżej.
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

8. **Blocks after the decision.** The report and the chat answer propose a
   change in words (`Co zrobić` of rule 4) and print no paste-ready block.
   A block has one of two sources. Once the user decides, the model prints the
   block with the skill's print-only `--block` after that decision, word for
   word. A skill without a `--block` printer gives, after the decision, the
   block from its own `SKILL.md` template, filled with values from the detail
   file and with every guard of the template kept (a stamped backup, the
   verify step, the abort, the rollback). After the decision the model puts
   either block, with its shell, its risk and its undo block, into a repair
   plan per `repair-plan.md` (`<data dir>/plans/`), checks the plan with
   `check_repair_plan.py` and tells the user which plan holds them. The plan
   still holds the blocks; they reach the user in `run-me.ps1` /
   `run-me-admin.ps1` in the cwd per `run-me.md`. The blocks never go into
   the chat or the report. Only where the skill has neither a
   printer nor a template for that change does the model give the step in
   words, also after the decision, in the repair plan. A skill whose format hands
   changes to another skill (processes hands ending and disabling to
   `ush-inventory`) names that skill and the entry's key.

   Good:

   ```markdown
   Gdy zdecydujesz, zapiszę plan naprawy z blokiem do wklejenia i blokiem cofającym.
   ```

   Bad:

   ```markdown
   Blok do wklejenia jest poniżej — wklej go teraz w powłoce administratora.
   ```

9. **Script commands.** Every block that runs a skill script has a
   `Set-Location` line with the absolute plugin root, and, on the same line as
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
