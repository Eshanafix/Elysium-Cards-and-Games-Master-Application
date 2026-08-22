"""
Tests use real product names/descriptions captured live from tcgcsv.com
during Phase 3 implementation (Foundations group 23556, Dominaria United
group 3102) so the regex patterns are validated against actual data, not
assumptions -- this exact class of bug (assumed API shape vs. real shape)
has bitten this project twice already.
"""

from elysium.models.products import (
    BOOSTER_TYPE_CLASSIC,
    BOOSTER_TYPE_COLLECTOR,
    BOOSTER_TYPE_DRAFT,
    BOOSTER_TYPE_JUMPSTART,
    BOOSTER_TYPE_PLAY,
    BOOSTER_TYPE_SET,
)
from elysium.services.tcgcsv_catalog_service import (
    classify_sealed_candidates,
    default_packs_per_box,
    derive_booster_type_from_name,
    parse_packs_per_box,
    suggest_product_name,
)

# Real product names from TCGCSV group 23556 ("Foundations", 2024+, uses
# "Display" wording and only has Play/Collector boosters).
FOUNDATIONS_PRODUCT_NAMES = [
    "Magic: The Gathering Foundations - Play Booster Pack",
    "Magic: The Gathering Foundations - Play Booster Display",
    "Magic: The Gathering Foundations - Play Booster Display Case",
    "Magic: The Gathering Foundations - Collector Booster Pack",
    "Magic: The Gathering Foundations - Collector Booster Display",
    "Magic: The Gathering Foundations - Collector Booster Display Case",
    "Magic: The Gathering Foundations - Collector Booster Display Master Case",
    "Magic: The Gathering Foundations - Bundle",
    "Magic: The Gathering Foundations - Bundle Case",
    "Magic: The Gathering Foundations - Beginner Box",
    "Magic: The Gathering Foundations - Beginner Box Case",
    "Magic: The Gathering Foundations - Collector Booster Omega Pack",
    "Magic: The Gathering Foundations - Sleeved Play Booster Pack",
    "Vampires Deck Theme Card",
    "Strongbox Raider",
]

# Real product names from TCGCSV group 3102 ("Dominaria United", 2022,
# uses "Box" wording for Draft/Set and "Display" for Collector -- the
# inconsistency this whole module exists to tolerate).
DOMINARIA_UNITED_PRODUCT_NAMES = [
    "Dominaria United - Draft Booster Box",
    "Dominaria United - Set Booster Pack",
    "Dominaria United - Collector Booster Pack",
    "Dominaria United - Collector Booster Display",
    "Dominaria United - Bundle",
    "Dominaria United - Jumpstart Booster Pack",
    "Dominaria United - Jumpstart Booster Display",
    "Dominaria United - Bundle Case",
    "Dominaria United - Set Booster Box",
    "Dominaria United - Set Booster Display Case",
    "Dominaria United - Draft Booster Pack",
    "Dominaria United - Draft Booster Box Case",
    "Dominaria United - Collector Booster Display Case",
    "Dominaria United - Jumpstart Booster Box Case",
    "Dominaria United - Box Topper Pack",
    "Dominaria United - Collector Booster Omega Pack",
    "Dominaria United - Collector Booster Sample Pack",
]


# Real product names from TCGCSV group 1791 ("Kaladesh", 2016) and group
# 2366 ("Ravnica Allegiance", 2019), captured live 2026-08-08. Pre-2020
# sets predate the Play/Draft/Set/Collector split entirely -- the only
# "normal" booster is a bare "<Set> - Booster Pack/Box", with no qualifier
# word. This is the exact bug report: search found the set, but the loose/
# box candidate dropdowns came back completely empty for these sets.
KALADESH_PRODUCT_NAMES = [
    "Kaladesh - Booster Box",
    "Kaladesh - Booster Box Case",
    "Kaladesh - Booster Pack",
    "Kaladesh - Two-Player Booster Battle Pack",
    "Kaladesh - Holiday Buy-a-Box Promo Pack",
]

RAVNICA_ALLEGIANCE_PRODUCT_NAMES = [
    "Ravnica Allegiance - Booster Box Case",
    "Ravnica Allegiance - Booster Box",
    "Ravnica Allegiance - Booster Pack",
    "Ravnica Allegiance - Theme Booster Pack [Azorius]",
    "Ravnica Allegiance - Theme Booster Pack [Set of 5]",
    "Ravnica Allegiance - Theme Booster Display Box",
    "Ravnica Allegiance - Prerelease Pack [Orzhov]",
    "Ravnica Allegiance - Collectors Booster Pack",
]

# Real product names from TCGCSV group 24421 ("Avatar: The Last Airbender",
# 2025) and group 23446 ("Universes Beyond: Assassin's Creed", 2025),
# captured live 2026-08-16. Bug report: Jumpstart and "Beyond" boosters are
# real, purchasable single-SKU sealed products, but the search flow's
# candidate dropdowns came back empty for them.
AVATAR_PRODUCT_NAMES = [
    "Avatar: The Last Airbender - Play Booster Pack",
    "Avatar: The Last Airbender - Play Booster Display",
    "Avatar: The Last Airbender - Play Booster Display Case",
    "Avatar: The Last Airbender - Collector Booster Pack",
    "Avatar: The Last Airbender - Collector Booster Display",
    "Avatar: The Last Airbender - Collector Booster Display Case",
    "Avatar: The Last Airbender - Jumpstart Booster 2-Pack",
    "Avatar: The Last Airbender - Jumpstart Booster Pack",
    "Avatar: The Last Airbender - Jumpstart Booster Display",
    "Avatar: The Last Airbender - Jumpstart Booster Display Case",
    "Avatar: The Last Airbender - Beginner Box",
    "Avatar: The Last Airbender - Prerelease Pack (Aang - White)",
    "Avatar: The Last Airbender - Collector Booster Omega Pack",
    "Avatar: The Last Airbender - Sleeved Play Booster Pack",
]

ASSASSINS_CREED_PRODUCT_NAMES = [
    "Universes Beyond: Assassin's Creed - Beyond Booster Pack",
    "Universes Beyond: Assassin's Creed - Beyond Booster Display",
    "Universes Beyond: Assassin's Creed - Beyond Booster Display Case",
    "Universes Beyond: Assassin's Creed - Collector Booster Pack",
    "Universes Beyond: Assassin's Creed - Collector Booster Display",
    "Universes Beyond: Assassin's Creed - Collector Booster Display Case",
    "Magic Minigame: Beyond Booster Blitz",
    "Universes Beyond: Assassin's Creed - Collector Booster Omega Pack",
]

# Real product names from TCGCSV group 2571 ("Mystery Booster: Retail
# Exclusives", abbreviation RMB1) and group 2570 ("Mystery Booster:
# Convention Edition Exclusives", abbreviation CMB1), captured live
# 2026-08-16. Bug report: "set code MB1 not showing up" -- TCGCSV's actual
# "Mystery Booster Cards" group (abbreviation MB1) has zero products under
# it at all; these two differently-abbreviated groups are where the real,
# purchasable Mystery Booster packs/boxes live. Their names also carry a
# bracketed/parenthesized annotation after "Booster Pack/Box" that the
# plain end-of-name anchor didn't tolerate.
MYSTERY_BOOSTER_RETAIL_PRODUCT_NAMES = [
    "Mystery Booster - Booster Pack [Retail Exclusive]",
    "Mystery Booster - Booster Box [Retail Exclusive]",
]

MYSTERY_BOOSTER_CONVENTION_PRODUCT_NAMES = [
    "Mystery Booster - Booster Pack [Convention Edition] (2019)",
    "Mystery Booster - Booster Box [Convention Edition] (2019)",
    "Mystery Booster - Booster Box [Convention Edition] (2021)",
    "Mystery Booster - Booster Pack [Convention Edition] (2021)",
    "Mystery Booster - Booster Box Case [Convention Edition] (2021)",
]


def make_products(names: list[str]) -> list[dict]:
    return [
        {"productId": 1000 + i, "name": name, "imageUrl": f"https://example.com/{i}.jpg"}
        for i, name in enumerate(names)
    ]


def test_foundations_loose_candidates_are_play_and_collector_only():
    products = make_products(FOUNDATIONS_PRODUCT_NAMES)
    loose, _box = classify_sealed_candidates(products)

    loose_names = {c.name for c in loose}
    # "Sleeved Play Booster Pack" is a real, distinct sellable product that
    # also genuinely ends in "Play Booster Pack" -- correctly included as
    # one more candidate; the admin picks the right one from a short list
    # rather than the system guessing which single-pack SKU is "the" one.
    assert loose_names == {
        "Magic: The Gathering Foundations - Play Booster Pack",
        "Magic: The Gathering Foundations - Sleeved Play Booster Pack",
        "Magic: The Gathering Foundations - Collector Booster Pack",
    }


def test_foundations_box_candidates_exclude_case_variants():
    products = make_products(FOUNDATIONS_PRODUCT_NAMES)
    _loose, box = classify_sealed_candidates(products)

    box_names = {c.name for c in box}
    assert box_names == {
        "Magic: The Gathering Foundations - Play Booster Display",
        "Magic: The Gathering Foundations - Collector Booster Display",
    }
    # "Display Case" and "Display Master Case" must NOT be candidates.
    assert not any("Case" in name for name in box_names)


def test_foundations_excludes_bundles_and_singles():
    products = make_products(FOUNDATIONS_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    all_names = {c.name for c in loose + box}
    assert "Magic: The Gathering Foundations - Bundle" not in all_names
    assert "Vampires Deck Theme Card" not in all_names
    assert "Strongbox Raider" not in all_names
    assert "Magic: The Gathering Foundations - Collector Booster Omega Pack" not in all_names


def test_dominaria_united_handles_box_wording_not_just_display():
    """The naming inconsistency this module exists to tolerate: Dominaria
    United's box products are named "...Booster Box", not "...Display"."""
    products = make_products(DOMINARIA_UNITED_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    loose_names = {c.name for c in loose}
    box_names = {c.name for c in box}

    assert loose_names == {
        "Dominaria United - Set Booster Pack",
        "Dominaria United - Collector Booster Pack",
        "Dominaria United - Draft Booster Pack",
        "Dominaria United - Jumpstart Booster Pack",
    }
    assert box_names == {
        "Dominaria United - Draft Booster Box",
        "Dominaria United - Collector Booster Display",
        "Dominaria United - Set Booster Box",
        "Dominaria United - Jumpstart Booster Display",
    }


def test_dominaria_united_excludes_sample_topper_bundle_and_omega():
    products = make_products(DOMINARIA_UNITED_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    all_names = {c.name for c in loose + box}
    assert "Dominaria United - Box Topper Pack" not in all_names
    assert "Dominaria United - Collector Booster Sample Pack" not in all_names
    assert "Dominaria United - Collector Booster Omega Pack" not in all_names
    assert "Dominaria United - Bundle" not in all_names
    assert "Dominaria United - Bundle Case" not in all_names


def test_dominaria_united_includes_jumpstart_pack_and_display_as_jumpstart_type():
    """Jumpstart boosters are a real, purchasable single-SKU sealed product
    -- they should show up as candidates (for a streamer who actually wants
    to open them), classified as their own JUMPSTART type. "Jumpstart
    Booster Box Case" (a bulk case) and "Jumpstart Booster 2-Pack" (a
    bundle, not "Booster Pack") must still be excluded."""
    products = make_products(DOMINARIA_UNITED_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    loose_by_name = {c.name: c for c in loose}
    box_by_name = {c.name: c for c in box}

    assert loose_by_name["Dominaria United - Jumpstart Booster Pack"].booster_type == BOOSTER_TYPE_JUMPSTART
    assert box_by_name["Dominaria United - Jumpstart Booster Display"].booster_type == BOOSTER_TYPE_JUMPSTART

    all_names = {c.name for c in loose + box}
    assert "Dominaria United - Jumpstart Booster Box Case" not in all_names


def test_kaladesh_pre_2020_set_has_no_qualifier_word_but_still_classifies():
    products = make_products(KALADESH_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    assert {c.name for c in loose} == {"Kaladesh - Booster Pack"}
    assert {c.name for c in box} == {"Kaladesh - Booster Box"}
    assert loose[0].booster_type == BOOSTER_TYPE_CLASSIC
    assert box[0].booster_type == BOOSTER_TYPE_CLASSIC


def test_kaladesh_excludes_case_and_battle_and_promo_variants():
    products = make_products(KALADESH_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    all_names = {c.name for c in loose + box}
    assert "Kaladesh - Booster Box Case" not in all_names
    assert "Kaladesh - Two-Player Booster Battle Pack" not in all_names
    assert "Kaladesh - Holiday Buy-a-Box Promo Pack" not in all_names


def test_ravnica_allegiance_bare_and_collectors_plural_both_classify():
    products = make_products(RAVNICA_ALLEGIANCE_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    loose_names = {c.name for c in loose}
    assert loose_names == {
        "Ravnica Allegiance - Booster Pack",
        "Ravnica Allegiance - Collectors Booster Pack",
    }
    assert {c.name for c in box} == {"Ravnica Allegiance - Booster Box"}

    by_name = {c.name: c for c in loose}
    assert by_name["Ravnica Allegiance - Booster Pack"].booster_type == BOOSTER_TYPE_CLASSIC
    assert by_name["Ravnica Allegiance - Collectors Booster Pack"].booster_type == BOOSTER_TYPE_COLLECTOR


def test_ravnica_allegiance_excludes_theme_prerelease_and_case_variants():
    products = make_products(RAVNICA_ALLEGIANCE_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    all_names = {c.name for c in loose + box}
    assert not any("Theme" in name for name in all_names)
    assert not any("Prerelease" in name for name in all_names)
    assert "Ravnica Allegiance - Booster Box Case" not in all_names


def test_derive_booster_type_from_name():
    assert derive_booster_type_from_name("Magic: The Gathering Foundations - Play Booster Pack") == BOOSTER_TYPE_PLAY
    assert derive_booster_type_from_name("Dominaria United - Draft Booster Box") == BOOSTER_TYPE_DRAFT
    assert derive_booster_type_from_name("Dominaria United - Set Booster Pack") == BOOSTER_TYPE_SET
    assert derive_booster_type_from_name("Dominaria United - Collector Booster Display") == BOOSTER_TYPE_COLLECTOR
    assert derive_booster_type_from_name("Dominaria United - Bundle") is None
    assert derive_booster_type_from_name("Kaladesh - Booster Pack") == BOOSTER_TYPE_CLASSIC
    assert derive_booster_type_from_name("Dominaria United - Jumpstart Booster Pack") == BOOSTER_TYPE_JUMPSTART
    assert derive_booster_type_from_name(
        "Universes Beyond: Assassin's Creed - Beyond Booster Pack"
    ) == BOOSTER_TYPE_CLASSIC


def test_avatar_jumpstart_and_sleeved_are_included_others_excluded():
    products = make_products(AVATAR_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    loose_names = {c.name for c in loose}
    box_names = {c.name for c in box}

    assert loose_names == {
        "Avatar: The Last Airbender - Play Booster Pack",
        "Avatar: The Last Airbender - Collector Booster Pack",
        "Avatar: The Last Airbender - Jumpstart Booster Pack",
        "Avatar: The Last Airbender - Sleeved Play Booster Pack",
    }
    assert box_names == {
        "Avatar: The Last Airbender - Play Booster Display",
        "Avatar: The Last Airbender - Collector Booster Display",
        "Avatar: The Last Airbender - Jumpstart Booster Display",
    }
    # "Jumpstart Booster 2-Pack" is a bundle, not a single "Booster Pack".
    all_names = loose_names | box_names
    assert "Avatar: The Last Airbender - Jumpstart Booster 2-Pack" not in all_names
    assert "Avatar: The Last Airbender - Beginner Box" not in all_names
    assert "Avatar: The Last Airbender - Collector Booster Omega Pack" not in all_names


def test_assassins_creed_beyond_booster_included_as_classic():
    products = make_products(ASSASSINS_CREED_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    loose_names = {c.name for c in loose}
    box_names = {c.name for c in box}

    assert loose_names == {
        "Universes Beyond: Assassin's Creed - Beyond Booster Pack",
        "Universes Beyond: Assassin's Creed - Collector Booster Pack",
    }
    assert box_names == {
        "Universes Beyond: Assassin's Creed - Beyond Booster Display",
        "Universes Beyond: Assassin's Creed - Collector Booster Display",
    }

    by_name = {c.name: c for c in loose}
    assert by_name["Universes Beyond: Assassin's Creed - Beyond Booster Pack"].booster_type == BOOSTER_TYPE_CLASSIC
    assert "Magic Minigame: Beyond Booster Blitz" not in (loose_names | box_names)


def test_mystery_booster_retail_bracket_suffix_is_tolerated():
    products = make_products(MYSTERY_BOOSTER_RETAIL_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    assert {c.name for c in loose} == {"Mystery Booster - Booster Pack [Retail Exclusive]"}
    assert {c.name for c in box} == {"Mystery Booster - Booster Box [Retail Exclusive]"}
    assert loose[0].booster_type == BOOSTER_TYPE_CLASSIC


def test_mystery_booster_convention_bracket_and_paren_suffix_is_tolerated():
    products = make_products(MYSTERY_BOOSTER_CONVENTION_PRODUCT_NAMES)
    loose, box = classify_sealed_candidates(products)

    loose_names = {c.name for c in loose}
    box_names = {c.name for c in box}

    assert loose_names == {
        "Mystery Booster - Booster Pack [Convention Edition] (2019)",
        "Mystery Booster - Booster Pack [Convention Edition] (2021)",
    }
    assert box_names == {
        "Mystery Booster - Booster Box [Convention Edition] (2019)",
        "Mystery Booster - Booster Box [Convention Edition] (2021)",
    }
    # The bulk case variant must still be excluded.
    assert "Mystery Booster - Booster Box Case [Convention Edition] (2021)" not in (loose_names | box_names)


def test_parse_packs_per_box_from_foundations_style_text():
    """Real (excerpted) description text captured live from tcgcsv.com for
    productId 562118 ("Foundations - Play Booster Display"). This text
    contains an earlier, unrelated "contains: 14" phrase (cards per pack,
    not packs per box) plus literal "<br>" markup between "contains:" and
    the real number -- both of which broke a naive first version of this
    parser (it returned 14 instead of 36)."""
    product = {
        "extendedData": [
            {
                "name": "OracleText",
                "value": (
                    "A full display of Play Boosters supports a Draft event, since it comes with "
                    "36 Magic: The Gathering Foundations Play Booster Packs; each Play Booster Pack "
                    "contains: 14 Magic: The Gathering cards\r\n<br>• Play Boosters may contain "
                    "these cards: FDN 1-361\r\n<br>\r\n<br>Magic: The Gathering Foundations - Play "
                    "Booster Box contains:\r\n<br>• 36 Magic: The Gathering—Magic: The "
                    "Gathering Foundations Play Boosters"
                ),
            }
        ]
    }
    assert parse_packs_per_box(product) == 36


def test_parse_packs_per_box_from_dominaria_style_text():
    product = {
        "extendedData": [
            {
                "name": "OracleText",
                "value": (
                    "The Dominaria United Draft Booster Display contains 36 Dominaria United "
                    "Draft Boosters and 1 Traditional Foil Box Topper card."
                ),
            }
        ]
    }
    assert parse_packs_per_box(product) == 36


def test_parse_packs_per_box_from_aetherdrift_style_text_prefers_the_last_match():
    """Real (excerpted) description text captured live from tcgcsv.com for
    productId 604250 ("Aetherdrift - Play Booster Display"). Contains an
    earlier, unrelated "Booster Display contains a 2-card First-Place Box
    Topper" sentence -- which the anchored pattern also matches, since it's
    "Booster Display contains" too -- followed by the real summary sentence
    near the end ("...Play Booster Box contains:<br> 30 ... Play Booster
    Packs"). Taking the first match (as a naive .search() does) silently
    returned 2 instead of 30 for this exact live product."""
    product = {
        "extendedData": [
            {
                "name": "OracleText",
                "value": (
                    "Play Boosters are one of the best ways to play Magic with friends.\r\n<br>"
                    "Plus, each Play Booster Display contains a 2-card First-Place Box Topper.\r\n<br>"
                    "<br>Aetherdrift - Play Booster Box contains:\r\n<br>. 30 Magic: The Gathering"
                    "-Aetherdrift Play Booster Packs"
                ),
            }
        ]
    }
    assert parse_packs_per_box(product) == 30


def test_parse_packs_per_box_ignores_unrelated_contains_phrases():
    """Regression test isolating the exact bug: a "Booster Pack contains:
    N cards" sentence (about the pack's card count) must never be mistaken
    for a "Booster Box/Display contains: N" sentence (the actual pack
    count per box) -- even when it's the only "contains" phrase present."""
    product = {
        "extendedData": [
            {
                "name": "OracleText",
                "value": "Each Play Booster Pack contains: 14 Magic: The Gathering cards.",
            }
        ]
    }
    assert parse_packs_per_box(product) is None


def test_parse_packs_per_box_returns_none_when_unparseable():
    product = {"extendedData": [{"name": "OracleText", "value": "No pack count mentioned here."}]}
    assert parse_packs_per_box(product) is None


def test_parse_packs_per_box_returns_none_with_no_extended_data():
    assert parse_packs_per_box({}) is None


def test_default_packs_per_box_by_type():
    assert default_packs_per_box(BOOSTER_TYPE_PLAY) == 36
    assert default_packs_per_box(BOOSTER_TYPE_DRAFT) == 36
    assert default_packs_per_box(BOOSTER_TYPE_SET) == 30
    assert default_packs_per_box(BOOSTER_TYPE_COLLECTOR) == 12


def test_suggest_product_name():
    assert suggest_product_name("Foundations", BOOSTER_TYPE_PLAY) == "Foundations Play Booster"
    assert suggest_product_name("Dominaria United", BOOSTER_TYPE_DRAFT) == "Dominaria United Draft Booster"


def test_suggest_product_name_classic_has_no_qualifier_word():
    """Matches how these are actually named on TCGCSV, e.g. "Kaladesh -
    Booster Pack", not "Kaladesh Classic Booster"."""
    assert suggest_product_name("Kaladesh", BOOSTER_TYPE_CLASSIC) == "Kaladesh Booster"


def test_default_packs_per_box_classic():
    assert default_packs_per_box(BOOSTER_TYPE_CLASSIC) == 36


def test_default_packs_per_box_jumpstart():
    assert default_packs_per_box(BOOSTER_TYPE_JUMPSTART) == 18
