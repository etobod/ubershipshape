"""Stable ``e`` ids of ush-settings across runs (plan 108, M3, K5).

Interface under test (from the plan; the general one is in ``fakes.py``):

- ``e`` takes its number from a map in ``<data dir>/state/ush-settings.ids.json``, keyed by
  the catalogue entry id. An entry that stays keeps its ``e`` id when another entry leaves
  the catalogue.
- On the first run with a map the numbers equal today's places after sorting.

Assumption added by this test: entries with the same state, area and level are sorted by
their entry id. The invented catalogue makes every other plausible sort key agree with
that order (catalogue order, titles and location names all ascend with the entry id), so
"the place after sorting" is the same whatever the sort uses.

Every value here is invented; nothing comes from a machine. PowerShell never starts.
"""

import unittest

from .fakes import (
    FakePowerShell,
    SettingsTestCase,
    loc,
    minutes,
    present,
    registry,
    registry_entry,
)

LETTERS = ("a", "b", "c", "d", "e")


def entry_id(letter):
    return f"invented_stable_{letter}"


def location(letter):
    return loc("HKCU", f"Software\\InventedVendor\\Stable{letter.upper()}",
               f"InventedStable{letter.upper()}", "preference")


def entries(letters):
    return [registry_entry(entry_id(letter), [location(letter)], expected=[0], default=1)
            for letter in letters]


def responses(letters):
    """Every entry differs from its expected value, so all have the same state."""
    return {"registry_values": registry(*(present(location(letter), 1)
                                          for letter in letters))}


class TestStableIds(SettingsTestCase):
    def ids_by_entry(self, summary):
        items = self.items_by_entry(self.detail(summary).get("settings"))
        return {entry: item.get("id") for entry, item in items.items()}

    def test_entry_ids_survive_catalogue_change(self):
        data_dir = self.data_dir()

        self.write_catalogue(entries(LETTERS))
        first = self.collect(FakePowerShell(responses(LETTERS)), data_dir=data_dir,
                             now=minutes(0))
        self.assertTrue((data_dir / "state" / "ush-settings.ids.json").is_file(),
                        "the id map was not written")
        first_ids = self.ids_by_entry(first)
        # First run: the numbers are the places after sorting.
        self.assertEqual(first_ids, {entry_id(letter): f"e{n}"
                                     for n, letter in enumerate(LETTERS, start=1)})
        for entry, item in self.summary_items(first).items():
            self.assertEqual(item.get("id"), first_ids.get(entry), item)

        # Second run: the first entry left the catalogue; the others keep their ids.
        remaining = LETTERS[1:]
        self.write_catalogue(entries(remaining))
        second = self.collect(FakePowerShell(responses(remaining)), data_dir=data_dir,
                              now=minutes(1))
        second_ids = self.ids_by_entry(second)
        self.assertEqual(second_ids, {entry_id(letter): first_ids[entry_id(letter)]
                                      for letter in remaining})
        for entry, item in self.summary_items(second).items():
            self.assertEqual(item.get("id"), second_ids.get(entry), item)


if __name__ == "__main__":
    unittest.main()
