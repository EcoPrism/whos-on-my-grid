"""Machine-readable marks that the card is AI-assisted. XMP (IPTC digital
source type) is always written; a signed C2PA manifest only when a signing
certificate is configured and the `c2pa` package imports. Platforms strip
both (X does, LinkedIn shows C2PA): the disclosure band in the pixels is the
guarantee, this is best effort."""

import io
import json
import struct
import zlib
from html import escape

from app.config import DRAFT_MODEL_ID, Settings
from app.telemetry import log_event

IPTC_COMPOSITE_AI = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
)
GENERATOR = "Who's on my grid"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_XMP_KEYWORD = b"XML:com.adobe.xmp"


def xmp_packet(*, source_type: str, description: str, link: str) -> str:
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about=""'
        ' xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        f' Iptc4xmpExt:DigitalSourceType="{escape(source_type)}"'
        f' xmp:CreatorTool="{escape(GENERATOR)}">'
        "<dc:description><rdf:Alt>"
        f'<rdf:li xml:lang="x-default">{escape(description)}</rdf:li>'
        "</rdf:Alt></dc:description>"
        f"<dc:source>{escape(link)}</dc:source>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
        '<?xpacket end="r"?>'
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def with_xmp(png: bytes, *, source_type: str, description: str, link: str) -> bytes:
    """Adds an iTXt chunk 'XML:com.adobe.xmp' with Iptc4xmpExt:DigitalSourceType,
    dc:description and a link. Always applied. Inserted before IEND; no time in
    it, so the bytes stay deterministic."""
    if not png.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG")
    # keyword NUL, compression flag 0, method 0, empty language NUL, empty translated NUL.
    text = xmp_packet(source_type=source_type, description=description, link=link)
    itxt = _chunk(b"iTXt", _XMP_KEYWORD + b"\x00\x00\x00\x00\x00" + text.encode("utf-8"))
    iend = png.rindex(b"IEND") - 4
    return png[:iend] + itxt + png[iend:]


_warned = False


def _skip(reason: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        log_event("c2pa_skipped", reason=reason)


def with_c2pa(png: bytes, *, settings: Settings) -> bytes:
    """Signs a C2PA manifest (c2pa.created, digitalSourceType as above, generator name and
    the model ids) when GRID_C2PA_CERT_PATH and the key from Key Vault are configured and
    the `c2pa` package imports. Otherwise returns png unchanged and logs once."""
    if not settings.c2pa_cert_path or not settings.c2pa_private_key:
        _skip("not_configured")
        return png
    try:
        import c2pa  # type: ignore[import-not-found]  # optional: see pyproject.toml
    except ImportError:
        _skip("package_missing")
        return png
    manifest = {
        "claim_generator_info": [{"name": GENERATOR}],
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": IPTC_COMPOSITE_AI,
                            "softwareAgent": {"name": GENERATOR},
                            "parameters": {"models": [DRAFT_MODEL_ID, settings.verify_model]},
                        }
                    ]
                },
            }
        ],
    }
    try:
        with open(settings.c2pa_cert_path, "rb") as f:
            certs = f.read()
        info = c2pa.C2paSignerInfo(
            alg=b"es256",
            sign_cert=certs,
            private_key=settings.c2pa_private_key.encode(),
            ta_url=settings.c2pa_timestamp_url.encode(),
        )
        signer = c2pa.Signer.from_info(info)
        builder = c2pa.Builder(json.dumps(manifest))
        out = io.BytesIO()
        builder.sign(signer, "image/png", io.BytesIO(png), out)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001  metadata is best effort; the pixels carry it
        log_event("c2pa_failed", kind=exc.__class__.__name__)
        return png
