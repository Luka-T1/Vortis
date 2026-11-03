"""Tests for AppleContactsConnector — local macOS Contacts database connector.

All tests use a temporary SQLite database that mimics the real AddressBook
schema.  No actual macOS Contacts database is required.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from vortis.connectors._stubs import Document
from vortis.core.registry import ConnectorRegistry


def _create_fake_contacts_db(db_path: Path) -> None:
    """Populate a SQLite file with the Apple Contacts schema and sample rows."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE ZABCDRECORD (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZISALL INTEGER,
            ZTYPE INTEGER,
            ZFIRSTNAME VARCHAR,
            ZMIDDLENAME VARCHAR,
            ZLASTNAME VARCHAR,
            ZORGANIZATION VARCHAR,
            ZJOBTITLE VARCHAR,
            ZDEPARTMENT VARCHAR,
            ZNICKNAME VARCHAR,
            ZBIRTHDAY TIMESTAMP,
            ZCREATIONDATE TIMESTAMP,
            ZMODIFICATIONDATE TIMESTAMP,
            ZUNIQUEID VARCHAR
        );

        CREATE TABLE ZABCDPHONENUMBER (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZISPRIMARY INTEGER,
            ZISPRIVATE INTEGER,
            ZORDERINGINDEX INTEGER,
            ZOWNER INTEGER,
            Z22_OWNER INTEGER,
            ZFULLNUMBER VARCHAR,
            ZLABEL VARCHAR,
            ZUNIQUEID VARCHAR,
            ZIOSLEGACYIDENTIFIER INTEGER
        );

        CREATE TABLE ZABCDEMAILADDRESS (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZISPRIMARY INTEGER,
            ZISPRIVATE INTEGER,
            ZORDERINGINDEX INTEGER,
            ZOWNER INTEGER,
            Z22_OWNER INTEGER,
            ZADDRESS VARCHAR,
            ZADDRESSNORMALIZED VARCHAR,
            ZLABEL VARCHAR,
            ZUNIQUEID VARCHAR,
            ZIOSLEGACYIDENTIFIER INTEGER
        );

        CREATE TABLE ZABCDPOSTALADDRESS (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZISPRIMARY INTEGER,
            ZISPRIVATE INTEGER,
            ZORDERINGINDEX INTEGER,
            ZOWNER INTEGER,
            Z22_OWNER INTEGER,
            ZSTREET VARCHAR,
            ZCITY VARCHAR,
            ZSTATE VARCHAR,
            ZZIPCODE VARCHAR,
            ZCOUNTRYNAME VARCHAR,
            ZLABEL VARCHAR,
            ZUNIQUEID VARCHAR,
            ZIOSLEGACYIDENTIFIER INTEGER
        );

        CREATE TABLE ZABCDURLADDRESS (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZISPRIMARY INTEGER,
            ZISPRIVATE INTEGER,
            ZORDERINGINDEX INTEGER,
            ZOWNER INTEGER,
            Z22_OWNER INTEGER,
            ZLABEL VARCHAR,
            ZUNIQUEID VARCHAR,
            ZURL VARCHAR,
            ZIOSLEGACYIDENTIFIER INTEGER
        );

        CREATE TABLE ZABCDSOCIALPROFILE (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZISPRIMARY INTEGER,
            ZISPRIVATE INTEGER,
            ZORDERINGINDEX INTEGER,
            ZOWNER INTEGER,
            Z22_OWNER INTEGER,
            ZUSERNAME VARCHAR,
            ZSERVICENAME VARCHAR,
            ZLABEL VARCHAR,
            ZUNIQUEID VARCHAR,
            ZIOSLEGACYIDENTIFIER INTEGER
        );

        CREATE TABLE ZABCDNOTE (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            Z_OPT INTEGER,
            ZCONTACT INTEGER,
            Z22_CONTACT INTEGER,
            ZTEXT VARCHAR
        );
    """)

    conn.execute(
        "INSERT INTO ZABCDRECORD "
        "(Z_PK, ZISALL, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION, "
        " ZCREATIONDATE, ZMODIFICATIONDATE, ZUNIQUEID) "
        "VALUES (1, 1, NULL, NULL, NULL, 700000000.0, 700000000.0, 'sys-all')"
    )

    conn.execute(
        "INSERT INTO ZABCDRECORD "
        "(Z_PK, ZFIRSTNAME, ZMIDDLENAME, ZLASTNAME, ZORGANIZATION, "
        " ZJOBTITLE, ZDEPARTMENT, ZNICKNAME, ZBIRTHDAY, "
        " ZCREATIONDATE, ZMODIFICATIONDATE, ZUNIQUEID) "
        "VALUES (2, 'Alice', 'M', 'Smith', 'Acme Corp', "
        " 'Engineer', 'R&D', 'Ali', 694310400.0, "
        " 694310400.0, 694396800.0, 'uid-alice')"
    )
    conn.execute(
        "INSERT INTO ZABCDPHONENUMBER "
        "(Z_PK, ZORDERINGINDEX, ZOWNER, ZFULLNUMBER, ZLABEL) "
        "VALUES (1, 0, 2, '+1-555-0100', '_$!<Mobile>!$_')"
    )
    conn.execute(
        "INSERT INTO ZABCDEMAILADDRESS "
        "(Z_PK, ZORDERINGINDEX, ZOWNER, ZADDRESS, ZLABEL) "
        "VALUES (1, 0, 2, 'alice@acme.com', '_$!<Work>!$_')"
    )
    conn.execute(
        "INSERT INTO ZABCDPOSTALADDRESS "
        "(Z_PK, ZORDERINGINDEX, ZOWNER, ZSTREET, ZCITY, ZSTATE, "
        " ZZIPCODE, ZCOUNTRYNAME, ZLABEL) "
        "VALUES (1, 0, 2, '123 Main St', 'Springfield', 'IL', "
        " '62704', 'United States', '_$!<Work>!$_')"
    )
    conn.execute(
        "INSERT INTO ZABCDURLADDRESS "
        "(Z_PK, ZORDERINGINDEX, ZOWNER, ZURL, ZLABEL) "
        "VALUES (1, 0, 2, 'https://alice.dev', '_$!<HomePage>!$_')"
    )
    conn.execute(
        "INSERT INTO ZABCDSOCIALPROFILE "
        "(Z_PK, ZORDERINGINDEX, ZOWNER, ZUSERNAME, ZSERVICENAME, ZLABEL) "
        "VALUES (1, 0, 2, '@alicesmith', 'Twitter', NULL)"
    )
    conn.execute(
        "INSERT INTO ZABCDNOTE (Z_PK, ZCONTACT, ZTEXT) "
        "VALUES (1, 2, 'Met at WWDC 2024')"
    )

    conn.execute(
        "INSERT INTO ZABCDRECORD "
        "(Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION, "
        " ZCREATIONDATE, ZMODIFICATIONDATE, ZUNIQUEID) "
        "VALUES (3, NULL, NULL, 'Acme Corp', "
        " 694310400.0, 694310400.0, 'uid-acme')"
    )
    conn.execute(
        "INSERT INTO ZABCDPHONENUMBER "
        "(Z_PK, ZORDERINGINDEX, ZOWNER, ZFULLNUMBER, ZLABEL) "
        "VALUES (2, 0, 3, '1-800-ACME', '_$!<Main>!$_')"
    )

    conn.execute(
        "INSERT INTO ZABCDRECORD "
        "(Z_PK, ZFIRSTNAME, ZLASTNAME, "
        " ZCREATIONDATE, ZMODIFICATIONDATE, ZUNIQUEID) "
        "VALUES (4, 'Bob', 'Jones', "
        " 694400000.0, 694500000.0, 'uid-bob')"
    )

    conn.commit()
    conn.close()


@pytest.fixture()
def fake_db(tmp_path: Path) -> Path:
    """Return path to a populated fake AddressBook database."""
    db_path = tmp_path / "AddressBook-v22.abcddb"
    _create_fake_contacts_db(db_path)
    return db_path


@pytest.fixture()
def connector(fake_db: Path):
    """AppleContactsConnector pointing at the fake DB."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    return AppleContactsConnector(db_path=str(fake_db))


def test_is_connected(connector) -> None:
    """is_connected() returns True when AddressBook database exists."""
    assert connector.is_connected() is True


def test_not_connected_missing_db() -> None:
    """is_connected() returns False when the database file does not exist."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    conn = AppleContactsConnector(db_path="/nonexistent/path/AddressBook.db")
    assert conn.is_connected() is False


def test_sync_yields_contacts(connector) -> None:
    """sync() yields one Document per real contact (3 total, skips system row)."""
    docs: List[Document] = list(connector.sync())
    assert len(docs) == 3
    for doc in docs:
        assert doc.source == "apple_contacts"
        assert doc.doc_type == "contact"


def test_sync_extracts_all_fields(connector) -> None:
    """sync() includes phone, email, address, URL, social, and notes in content."""
    docs: List[Document] = list(connector.sync())
    alice = next(d for d in docs if d.doc_id == "apple_contacts:uid-alice")

    assert "Alice M Smith" in alice.content
    assert "+1-555-0100" in alice.content
    assert "alice@acme.com" in alice.content
    assert "123 Main St" in alice.content
    assert "Springfield" in alice.content
    assert "https://alice.dev" in alice.content
    assert "@alicesmith" in alice.content
    assert "Met at WWDC 2024" in alice.content


def test_sync_cleans_labels(connector) -> None:
    """sync() strips _$!<Label>!$_ markup from content."""
    docs: List[Document] = list(connector.sync())
    alice = next(d for d in docs if d.doc_id == "apple_contacts:uid-alice")

    assert "_$!<" not in alice.content
    assert ">!$_" not in alice.content
    assert "Mobile" in alice.content
    assert "Work" in alice.content


def test_org_only_contact(connector) -> None:
    """A contact with only an organization name uses it as the title."""
    docs: List[Document] = list(connector.sync())
    acme = next(d for d in docs if d.doc_id == "apple_contacts:uid-acme")

    assert acme.title == "Acme Corp"
    assert "1-800-ACME" in acme.content


def test_minimal_contact(connector) -> None:
    """A contact with only a name still syncs correctly."""
    docs: List[Document] = list(connector.sync())
    bob = next(d for d in docs if d.doc_id == "apple_contacts:uid-bob")

    assert bob.title == "Bob Jones"
    assert bob.content.strip() == "Bob Jones"


def test_sync_since_filter(connector) -> None:
    """sync(since=...) skips contacts modified before the given datetime."""
    cutoff = datetime(2023, 1, 3, 12, 0, 0, tzinfo=timezone.utc)
    docs: List[Document] = list(connector.sync(since=cutoff))

    ids = {d.doc_id for d in docs}
    assert "apple_contacts:uid-bob" in ids
    assert "apple_contacts:uid-alice" not in ids


def test_sync_status(connector) -> None:
    """sync_status() reports items_synced and items_total after sync."""
    list(connector.sync())
    status = connector.sync_status()

    assert status.items_synced == 3
    assert status.items_total == 3
    assert status.last_sync is not None


def test_metadata_fields(connector) -> None:
    """Documents include structured metadata with name components."""
    docs: List[Document] = list(connector.sync())
    alice = next(d for d in docs if d.doc_id == "apple_contacts:uid-alice")

    assert alice.metadata["first_name"] == "Alice"
    assert alice.metadata["last_name"] == "Smith"
    assert alice.metadata["organization"] == "Acme Corp"
    assert alice.metadata["job_title"] == "Engineer"
    assert alice.metadata["nickname"] == "Ali"


def test_disconnect(connector) -> None:
    """disconnect() marks the connector as disconnected."""
    assert connector.is_connected() is True
    connector.disconnect()
    assert connector._connected is False


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 2 tools with the expected names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 2
    assert "contacts_search" in names
    assert "contacts_get_contact" in names


def test_registry() -> None:
    """AppleContactsConnector is registered and retrievable."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    ConnectorRegistry.register_value("apple_contacts", AppleContactsConnector)
    assert ConnectorRegistry.contains("apple_contacts")
    cls = ConnectorRegistry.get("apple_contacts")
    assert cls.connector_id == "apple_contacts"


def test_sync_empty_db(tmp_path: Path) -> None:
    """sync() yields nothing when the database has no contacts."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    db_path = tmp_path / "Empty.abcddb"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE ZABCDRECORD (
            Z_PK INTEGER PRIMARY KEY, ZFIRSTNAME VARCHAR,
            ZMIDDLENAME VARCHAR, ZLASTNAME VARCHAR,
            ZORGANIZATION VARCHAR, ZJOBTITLE VARCHAR,
            ZDEPARTMENT VARCHAR, ZNICKNAME VARCHAR,
            ZBIRTHDAY TIMESTAMP, ZCREATIONDATE TIMESTAMP,
            ZMODIFICATIONDATE TIMESTAMP, ZUNIQUEID VARCHAR
        );
        CREATE TABLE ZABCDPHONENUMBER (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
            ZORDERINGINDEX INTEGER, ZFULLNUMBER VARCHAR, ZLABEL VARCHAR
        );
        CREATE TABLE ZABCDEMAILADDRESS (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
            ZORDERINGINDEX INTEGER, ZADDRESS VARCHAR, ZLABEL VARCHAR
        );
        CREATE TABLE ZABCDPOSTALADDRESS (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
            ZORDERINGINDEX INTEGER, ZSTREET VARCHAR, ZCITY VARCHAR,
            ZSTATE VARCHAR, ZZIPCODE VARCHAR, ZCOUNTRYNAME VARCHAR,
            ZLABEL VARCHAR
        );
        CREATE TABLE ZABCDURLADDRESS (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
            ZORDERINGINDEX INTEGER, ZURL VARCHAR, ZLABEL VARCHAR
        );
        CREATE TABLE ZABCDSOCIALPROFILE (
            Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
            ZORDERINGINDEX INTEGER, ZUSERNAME VARCHAR,
            ZSERVICENAME VARCHAR, ZLABEL VARCHAR
        );
        CREATE TABLE ZABCDNOTE (
            Z_PK INTEGER PRIMARY KEY, ZCONTACT INTEGER, ZTEXT VARCHAR
        );
    """)
    conn.close()

    c = AppleContactsConnector(db_path=str(db_path))
    docs = list(c.sync())
    assert docs == []


def test_sync_missing_db() -> None:
    """sync() yields nothing when the database file doesn't exist."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    c = AppleContactsConnector(db_path="/nonexistent/AddressBook.db")
    docs = list(c.sync())
    assert docs == []


_MINIMAL_SCHEMA = """
    CREATE TABLE ZABCDRECORD (
        Z_PK INTEGER PRIMARY KEY, ZFIRSTNAME VARCHAR,
        ZMIDDLENAME VARCHAR, ZLASTNAME VARCHAR,
        ZORGANIZATION VARCHAR, ZJOBTITLE VARCHAR,
        ZDEPARTMENT VARCHAR, ZNICKNAME VARCHAR,
        ZBIRTHDAY TIMESTAMP, ZCREATIONDATE TIMESTAMP,
        ZMODIFICATIONDATE TIMESTAMP, ZUNIQUEID VARCHAR
    );
    CREATE TABLE ZABCDPHONENUMBER (
        Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
        ZORDERINGINDEX INTEGER, ZFULLNUMBER VARCHAR, ZLABEL VARCHAR
    );
    CREATE TABLE ZABCDEMAILADDRESS (
        Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
        ZORDERINGINDEX INTEGER, ZADDRESS VARCHAR, ZLABEL VARCHAR
    );
    CREATE TABLE ZABCDPOSTALADDRESS (
        Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
        ZORDERINGINDEX INTEGER, ZSTREET VARCHAR, ZCITY VARCHAR,
        ZSTATE VARCHAR, ZZIPCODE VARCHAR, ZCOUNTRYNAME VARCHAR,
        ZLABEL VARCHAR
    );
    CREATE TABLE ZABCDURLADDRESS (
        Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
        ZORDERINGINDEX INTEGER, ZURL VARCHAR, ZLABEL VARCHAR
    );
    CREATE TABLE ZABCDSOCIALPROFILE (
        Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER,
        ZORDERINGINDEX INTEGER, ZUSERNAME VARCHAR,
        ZSERVICENAME VARCHAR, ZLABEL VARCHAR
    );
    CREATE TABLE ZABCDNOTE (
        Z_PK INTEGER PRIMARY KEY, ZCONTACT INTEGER, ZTEXT VARCHAR
    );
"""


def _create_minimal_db(db_path: Path, contacts: list[tuple]) -> None:
    """Create a DB with given contacts: [(pk, first, last, org, uid), ...]."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_MINIMAL_SCHEMA)
    for pk, first, last, org, uid in contacts:
        conn.execute(
            "INSERT INTO ZABCDRECORD "
            "(Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION, "
            " ZCREATIONDATE, ZMODIFICATIONDATE, ZUNIQUEID) "
            f"VALUES ({pk}, ?, ?, ?, 694310400.0, 694310400.0, ?)",
            (first, last, org, uid),
        )
    conn.commit()
    conn.close()


def test_sync_reads_source_databases(tmp_path: Path) -> None:
    """sync() reads contacts from Sources/<UUID>/ databases."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    main_db = tmp_path / "AddressBook-v22.abcddb"
    _create_minimal_db(main_db, [(1, "Local", "Contact", None, "uid-local")])

    source_dir = tmp_path / "Sources" / "FAKE-UUID-1"
    source_dir.mkdir(parents=True)
    _create_minimal_db(
        source_dir / "AddressBook-v22.abcddb",
        [
            (1, "Cloud", "One", None, "uid-cloud1"),
            (2, "Cloud", "Two", None, "uid-cloud2"),
        ],
    )

    c = AppleContactsConnector(db_path=str(main_db))
    docs = list(c.sync())

    assert len(docs) == 3
    ids = {d.doc_id for d in docs}
    assert "apple_contacts:uid-local" in ids
    assert "apple_contacts:uid-cloud1" in ids
    assert "apple_contacts:uid-cloud2" in ids


def test_sync_deduplicates_across_sources(tmp_path: Path) -> None:
    """sync() deduplicates contacts that appear in multiple databases."""
    from vortis.connectors.apple_contacts import AppleContactsConnector

    main_db = tmp_path / "AddressBook-v22.abcddb"
    _create_minimal_db(main_db, [(1, "Alice", "Smith", None, "uid-alice")])

    source_dir = tmp_path / "Sources" / "FAKE-UUID-1"
    source_dir.mkdir(parents=True)
    _create_minimal_db(
        source_dir / "AddressBook-v22.abcddb",
        [
            (1, "Alice", "Smith", None, "uid-alice"),
            (2, "Bob", "Jones", None, "uid-bob"),
        ],
    )

    c = AppleContactsConnector(db_path=str(main_db))
    docs = list(c.sync())

    assert len(docs) == 2
    ids = {d.doc_id for d in docs}
    assert "apple_contacts:uid-alice" in ids
    assert "apple_contacts:uid-bob" in ids
