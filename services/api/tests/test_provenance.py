"""C2PA on the share card: signed with an ES256 chain when a certificate and key are
configured, read back with c2pa.Reader; otherwise, or when signing fails, the PNG goes
out unchanged and the log names the failure without the key. No network: the
timestamp URL is empty, which signs without a timestamp."""

import datetime as dt
import io
import json
import logging

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image

from app.brief import fixtures
from app.card import CardCache, make_png, provenance
from app.card.provenance import GENERATOR, IPTC_COMPOSITE_AI, signing_stamp, with_c2pa
from app.card.spec import spec_from_brief
from app.config import DRAFT_MODEL_ID
from tests import fakes

LINK = "https://g.example/b/3fb95348f1d4081e"


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Grid test"),
        ]
    )


def _chain() -> tuple[str, str]:
    """A test CA and an end-entity signer, as c2pa-rs wants them: the signer is not
    self-signed, has digitalSignature key usage and an EKU (emailProtection), and the
    chain is end-entity first. Structurally valid; untrusted, since no list holds the CA."""
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("Grid test CA"))
        .issuer_name(_name("Grid test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name("Grid test signer"))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, False, False, False, False),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    chain = leaf.public_bytes(pem) + ca.public_bytes(pem)
    private = key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return chain.decode(), private.decode()


@pytest.fixture(scope="module")
def chain() -> tuple[str, str]:
    return _chain()


def _card(tmp_path):
    spec = spec_from_brief(fixtures.by_key("ashburn"), public_base_url="https://g.example")
    return make_png(spec, link=LINK, settings=fakes.settings(tmp_path))


def _manifest(signed: bytes) -> dict:
    c2pa = pytest.importorskip("c2pa")
    with c2pa.Reader("image/png", io.BytesIO(signed)) as reader:
        store = json.loads(reader.json())
    return store["manifests"][store["active_manifest"]]


def test_signs_card_and_reads_back(tmp_path, chain) -> None:
    pytest.importorskip("c2pa")
    cert, key = chain
    png = _card(tmp_path)
    settings = fakes.settings(
        tmp_path, c2pa_cert_pem=cert, c2pa_private_key=key, c2pa_timestamp_url=""
    )
    signed = with_c2pa(png, settings=settings)
    assert signed != png
    Image.open(io.BytesIO(signed)).load()  # still a PNG

    manifest = _manifest(signed)
    assert manifest["claim_generator_info"][0]["name"] == GENERATOR
    actions = [
        a
        for assertion in manifest["assertions"]
        if assertion["label"].startswith("c2pa.actions")
        for a in assertion["data"]["actions"]
    ]
    created = next(a for a in actions if a["action"] == "c2pa.created")
    assert created["digitalSourceType"] == IPTC_COMPOSITE_AI
    assert created["softwareAgent"]["name"] == GENERATOR
    assert created["parameters"]["models"] == [DRAFT_MODEL_ID, settings.verify_model]
    assert manifest["signature_info"]["alg"].lower() == "es256"
    assert manifest["signature_info"]["common_name"] == "Grid test signer"
    # The XMP written before signing survives.
    assert b"XML:com.adobe.xmp" in signed


def test_cert_from_file_and_blank_secrets(tmp_path, chain) -> None:
    pytest.importorskip("c2pa")
    cert, key = chain
    path = tmp_path / "chain.pem"
    path.write_text(cert)
    png = _card(tmp_path)
    settings = fakes.settings(
        tmp_path, c2pa_cert_path=str(path), c2pa_private_key=key, c2pa_timestamp_url=""
    )
    assert _manifest(with_c2pa(png, settings=settings))["claim_generator_info"]
    # The secrets phase writes one space for "no certificate": that is off, not an error.
    blank = fakes.settings(tmp_path, c2pa_cert_pem=" ", c2pa_private_key=" ")
    assert with_c2pa(png, settings=blank) == png
    assert signing_stamp(blank) == ""
    assert len(signing_stamp(settings)) == 6


def test_unreachable_timestamp_signs_without_one(tmp_path, chain, monkeypatch) -> None:
    c2pa = pytest.importorskip("c2pa")
    cert, key = chain
    png = _card(tmp_path)
    calls: list[str] = []
    real = provenance._sign

    def sign(lib, png, manifest, chain, key, ta_url):
        calls.append(ta_url)
        if ta_url:
            raise c2pa.C2paError("timestamp authority unreachable")
        return real(lib, png, manifest, chain, key, ta_url)

    monkeypatch.setattr(provenance, "_sign", sign)
    settings = fakes.settings(
        tmp_path,
        c2pa_cert_pem=cert,
        c2pa_private_key=key,
        c2pa_timestamp_url="http://tsa.invalid",
    )
    signed = with_c2pa(png, settings=settings)
    assert calls == ["http://tsa.invalid", ""]
    assert _manifest(signed)["claim_generator_info"][0]["name"] == GENERATOR


def test_not_configured_returns_png_unchanged(tmp_path) -> None:
    png = _card(tmp_path)
    settings = fakes.settings(tmp_path)
    assert with_c2pa(png, settings=settings) == png
    assert signing_stamp(settings) == ""
    # Unsigned cards stay deterministic, so the cached file and its ETag hold.
    assert _card(tmp_path) == png


def test_broken_key_returns_png_and_logs_without_key(tmp_path, chain, caplog) -> None:
    pytest.importorskip("c2pa")
    cert, _ = chain
    bad = "-----BEGIN PRIVATE KEY-----\nTOPSECRETnotakey\n-----END PRIVATE KEY-----\n"
    png = _card(tmp_path)
    settings = fakes.settings(
        tmp_path, c2pa_cert_pem=cert, c2pa_private_key=bad, c2pa_timestamp_url=""
    )
    with caplog.at_level(logging.INFO):
        assert with_c2pa(png, settings=settings) == png
    assert "c2pa_failed" in caplog.text
    assert "TOPSECRET" not in caplog.text
    # Nor does the settings object print it.
    assert "TOPSECRET" not in repr(settings) and "TOPSECRET" not in str(settings)


def test_missing_cert_file_logs_and_returns_png(tmp_path, caplog) -> None:
    png = _card(tmp_path)
    settings = fakes.settings(
        tmp_path, c2pa_cert_path=str(tmp_path / "absent.pem"), c2pa_private_key="k"
    )
    with caplog.at_level(logging.INFO):
        assert with_c2pa(png, settings=settings) == png
    assert "c2pa_failed" in caplog.text
    assert signing_stamp(settings) == ""


def test_card_cache_keyed_by_signing(tmp_path) -> None:
    unsigned, signed = CardCache(tmp_path), CardCache(tmp_path, signing="ab12cd")
    unsigned.put("brief", "0123456789abcdef", b"plain", "ab12")
    assert signed.get("brief", "0123456789abcdef", "ab12") is None
    signed.put("brief", "0123456789abcdef", b"signed", "ab12")
    assert signed.get("brief", "0123456789abcdef", "ab12") == b"signed"
    assert unsigned.get("brief", "0123456789abcdef", "ab12") == b"plain"
    assert CardCache(tmp_path, signing="../x").signing == ""
