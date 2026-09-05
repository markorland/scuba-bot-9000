"""The guardrail is only known to work if it has been watched to fail.

Note the `addr()` helper. This file needs addresses on non-reserved domains to
prove they are caught, but `check_pii.py` scans the whole tree including its own
tests — and exempting this file would make it the one place a real address could
hide. So the literals never appear; they are assembled at runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_pii import forbidden_path, is_allowed, mask, scan_text  # noqa: E402

ALLOWLIST = {"noreply@github.com", "users.noreply.github.com"}


def addr(local: str, domain: str) -> str:
    """Assemble an address so no email-shaped literal exists in this file."""
    return local + "@" + domain


class TestDetection:
    def test_real_address_is_flagged(self) -> None:
        found = scan_text("contact: " + addr("someone", "gmail.com"), ALLOWLIST)
        assert len(found) == 1
        assert found[0][0] == 1

    def test_address_in_prose_is_flagged(self) -> None:
        text = "The roster lists " + addr("b.swift", "somecompany.co.uk") + " as primary."
        assert len(scan_text(text, ALLOWLIST)) == 1

    def test_line_numbers_are_reported(self) -> None:
        found = scan_text("clean\nclean\n" + addr("bad", "realdomain.com") + "\n", ALLOWLIST)
        assert found[0][0] == 3

    def test_several_on_one_line(self) -> None:
        line = addr("a", "realone.com") + " and " + addr("b", "realtwo.com")
        assert len(scan_text(line, ALLOWLIST)) == 2

    def test_a_subdomain_of_a_real_domain_is_still_real(self) -> None:
        assert not is_allowed(addr("x", "mail.realdomain.com"), set())


class TestAllowed:
    @pytest.mark.parametrize(
        "address",
        [
            "nadia@example.org",
            "owen@example.com",
            "betsy@example.net",
            "someone@work.example.org",  # subdomain of a reserved domain
            "bot@scubabot.test",
            "user@host.invalid",
            "dev@my.localhost",
            "anything@corp.example",
        ],
    )
    def test_reserved_domains_are_allowed(self, address: str) -> None:
        assert is_allowed(address, set())
        assert scan_text(f"email: {address}", set()) == []

    def test_explicit_allowlist_entry(self) -> None:
        assert is_allowed("noreply@github.com", ALLOWLIST)

    def test_allowlisted_bare_domain_covers_any_local_part(self) -> None:
        assert is_allowed("anyone@users.noreply.github.com", ALLOWLIST)

    def test_allowlist_is_case_insensitive(self) -> None:
        assert is_allowed("NoReply@GitHub.com", ALLOWLIST)

    def test_not_every_at_sign_is_an_address(self) -> None:
        assert scan_text("uses actions/checkout@v4 and @mentions", set()) == []


class TestMasking:
    """The check runs in public CI, so its output must not publish the address."""

    def test_local_part_and_domain_are_hidden(self) -> None:
        masked = mask(addr("b.swift", "somecompany.com"))
        assert "swift" not in masked
        assert "somecompany" not in masked

    def test_enough_survives_to_identify_it(self) -> None:
        assert mask(addr("betsy", "gmail.com")) == "b****@g****.com"

    def test_findings_are_masked(self) -> None:
        ((_, reported),) = scan_text("owner: " + addr("betsy", "gmail.com"), set())
        assert "betsy" not in reported
        assert "gmail" not in reported

    def test_a_masked_address_does_not_itself_trip_the_check(self) -> None:
        """Otherwise the check would flag its own output when logs are committed."""
        assert scan_text(mask(addr("betsy", "gmail.com")), set()) == []


class TestForbiddenPaths:
    @pytest.mark.parametrize(
        "path",
        [
            "roster.yaml",
            "roster.yml",
            "config/roster.yaml",
            "config/config.yaml",
            "data/scubabot.db",
            "data/scubabot.sqlite3",
            ".env",
            ".env.production",
            "snapshots/2026-03-08.sql",
            "tests/fixtures/real/aquarium-sunday.eml",
        ],
    )
    def test_rejected(self, path: str) -> None:
        assert forbidden_path(path) is not None

    @pytest.mark.parametrize(
        "path",
        [
            "PLAN.md",
            "config/config.example.yaml",
            "src/scubabot/fairness.py",
            "tests/fixtures/two-blocks.eml",
            ".github/workflows/ci.yml",
        ],
    )
    def test_allowed(self, path: str) -> None:
        assert forbidden_path(path) is None
